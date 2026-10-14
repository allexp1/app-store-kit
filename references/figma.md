# Figma: seeding, composing and exporting the frames

Proven end to end on 2026-10-14 (spike: one iPhone 1206 × 2622 frame and one iPad 2064 × 2752 frame,
both exported at exact size and passing `validate_kit.py`). Figma is the default **final renderer** when the
human wants to design there. The HTML renderer (`render.py`) is the fallback, and it also serves as a CI cross-check.
Only app UI and the generated sample library ever go to Figma. Never the user's own photos.

## 0. Before any `use_figma` call

- **Load the `/figma-use` skill first.** The Figma MCP server makes it mandatory.
  - If the Figma plugin is installed, the skill is listed as `figma-use` or `/figma-use`.
  - Otherwise read the MCP resource `skill://figma/figma-use/SKILL.md`.
- **If neither can be loaded, don't call `use_figma`.** Seed and export with the other tools below, and do bezels, locking and variables by hand or skip them.
  (In the spike neither could be loaded, so `use_figma`, `exportAsync` and `exportSettings` are untested.)
- `create_new_file` needs a plan key: get it from `whoami` or the team. Pass `editorType: design`.

## 1. Seed frames from HTML (`html_to_figma`)

1. Run `render.py KIT/frames.yaml --html-only`. It writes `KIT/html/<locale>/<slot>/figma-seed.html`: every frame of one set on one page, with captures inlined as data URIs and each frame rooted in `class="frame"`.
2. Call `html_to_figma` with `fileKey` and `cssSelector: ".frame"`. It returns a `submitUrl`.
3. POST the HTML yourself:
   `curl -X POST "<submitUrl>" -H 'Content-Type: text/html' --data-binary @figma-seed.html`
   It returns `{"nodeIds": ["1:2", …]}`. About 1 MB with two captures took about 10 s.
4. What you get:
   - frames at exactly the HTML size;
   - the caption as a real, editable text layer;
   - the capture as an image fill at full resolution (it downloads back at 1206 × 2622).

Known differences from the HTML render:
- **Font.** SF Pro isn't available to the Figma agent, so Figma substitutes an Inter-like face.
  Fix: upload SF Pro to the team, use local-font access, or set the font explicitly in `use_figma`.
- **Wrapping.** Figma ignores `text-wrap: balance`, so line breaks can differ from Chrome. Check every long caption by eye in both.
- **Fractional coordinates.** `html_to_figma` keeps fractional positions (for example y = 573.78). `render.py` writes whole pixels only; keep any hand-written HTML on whole pixels too.

## 2. Compose with Apple's components (needs `/figma-use`)

- `get_libraries` on the file lists Apple's **"iOS and iPadOS 27"** community library as available to add (Apple's iOS/iPadOS 27 kit, 17 September 2026).
- `search_design_system` in that library finds these component sets: "iPhone 17", "iPhone 17 Pro", "iPhone 17 Pro Max", "iPad Pro M4 13\"", "Status bar - iPhone 17 Pro" and "Status bar - iPhone Duo".
  Search again for the keys; don't hard-code them.
- Then, in `use_figma` (Plugin API):
  1. `importComponentSetByKeyAsync(key)`, place an instance, and put the capture inside its screen slot;
  2. set `locked = true` on the capture layer, because screens must stay what the app rendered (2.3.3);
  3. bind captions to variables, one mode per locale;
  4. set the caption font.
- Whether that library carries Apple's **photographic product bezels** (iPhone 18 and Duo, published 18 September 2026) is unverified.
  Those bezels are a separate download from <https://developer.apple.com/design/resources/> that **the human makes** and accepts the licence for. Never download them automatically.
- Apple's marketing guidelines (read 2026-10-14, https://developer.apple.com/app-store/marketing/guidelines/) govern how a bezel may be used: as is, never tilted, cropped, obstructed, flipped, shadowed or given reflections; captions beside the device, not on it; at least 200 px tall; never a 3D render or a drawn imitation of an Apple device; no competing products in the same frame. If a frame needs a perspective or 3D look, drop the device and show the screen flat instead.
- Edits made in Figma come back to `frames.yaml` only as a deliberate step (`get_design_context` → update YAML), never silently.

## 3. Export at exact size

| Call | Result |
|---|---|
| `download_assets(fileKey, nodeId)` with **no scale** (scale 1) → `curl -L -o out.png "<export.url>"` | exact frame size (1206 × 2622, 2064 × 2752) |
| `get_screenshot(fileKey, nodeId, maxDimension: <frame height>)` | the same size, **pixel-identical** to `download_assets`. Use it as a cross-check |

- Both come back **RGBA (fully opaque) with no ICC profile**, which App Store Connect rejects. **Always strip alpha after export:**
  `validate_kit.py --pairs --fix iphone-di-medium=out.png`, or run on the whole kit with `--fix`.
- Never pass a scale other than 1. Never trust a size you haven't measured: the validator measures every file.

## 4. Cross-check against HTML

- Render the same frames with `render.py`, then compare the device region.
  The spike measured a mean absolute difference of 0.16 (iPhone) and 0.07 (iPad): only edge antialiasing.
- A large difference in the caption region means font substitution or a different wrap. Fix it in Figma before export.
- If bezels can't be placed or locked through the API, switch: HTML becomes the final renderer and Figma becomes the review copy. Nothing else in the chain changes.
