# Sample photo library and art with Codex image generation

Screenshots need attractive content that belongs to nobody. **The user's real photos, contacts or library data
are never sent to OpenAI, Figma or any other service.** Only generated images and the app's UI leave the machine.

## The recipe that was used (Codex CLI 0.162.1, ChatGPT login, `image_generation` on)

```bash
mkdir -p KIT/samples/raw
codex exec --sandbox workspace-write -C KIT/samples/raw \
  "Use your image generation tool to create exactly 3 photorealistic images and save them as PNG files in the \
current directory named dog-beach.png, omelet.png, hike.png. Prompts: (1) '…' (2) '…' (3) '…'. \
After saving, list the files with their pixel sizes. Do nothing else."
```

- `--sandbox workspace-write -C <dir>` lets Codex write only into that directory. Approval stays at "never" in exec mode.
- Codex keeps its own copies in `~/.codex/generated_images/<session-id>/` and then copies them into `<dir>`.
- **Output is 1086 × 1448 PNG** (3:4 portrait) for a "portrait 3:4" prompt. Three images took about a minute and about 25k tokens.
- Ask for several distinct images in one call: one prompt per image, named files, "do nothing else".
- Budget about 60–80 images per library on a ChatGPT plan. Generate in small batches, and curate between them.

## Prompt rules (from Codex's review of the plan, and OpenAI's image-prompting guide)

1. **Casual phone photo, not stock.** Write "Photorealistic casual smartphone photo", handheld, a 26 mm-equivalent wide lens, deep focus, off-centre subject, slightly tilted horizon, natural or uneven light, mild noise or motion blur, muted everyday colours.
2. **Always negative-list:** no interface, lettering, text, logos, watermark, readable packaging, cinematic grading, studio lighting, portrait-mode bokeh or "advertising composition".
3. **No people,** or no identifiable people. Never a real person's likeness. No real brands or logos.
4. **Anchors plus edited follow-ups.** About 15 anchor photos, each a small story: one dog, one kitchen, one hike, one weekend away. Make the follow-ups by *editing the anchor* ("half a second later, the dog has turned its head"), so the library looks like one person's camera roll.
5. **Exact duplicates are file copies.** Make blur, dark and pocket shots with code (Pillow blur or exposure), not with the generator.
6. **No documents from the generator.** No boarding passes, receipts or IDs. A shopping list or recipe is *designed* (HTML or Figma) and marked SAMPLE.
7. **Coherent metadata.** Each photo gets plausible EXIF dates and places that fit its story, and sizes that match a phone (crop or upscale as needed).
8. **Content only.** Generated images appear *inside* the app's real screens, never as fake UI (2.3.3, 2.3.7).

Example anchor prompt that worked:
> Photorealistic casual smartphone photo from a fictional adult's camera roll. Their scruffy tan dog with a plain
> teal collar runs beside wet sand on an ordinary overcast afternoon. Handheld 26 mm-equivalent wide camera, mostly
> deep focus, slightly tilted horizon, dog off-center, slight paw motion blur, muted natural colors. One 3:4 portrait
> photograph; no interface, lettering, logos, watermark, cinematic grading, studio lighting, or portrait-mode bokeh.

## Provenance manifest (`KIT/samples/manifest.yaml`), required

"AI-generated" alone doesn't mean rights-clear. Every file gets an entry:

```yaml
- file: dog-beach.png
  sha256: <hash of the file as used>
  kind: generated            # generated | edited-from:<file> | derived-by-code:<file> | designed
  prompt: "Photorealistic casual smartphone photo …"
  model: <model name from the codex log header, e.g. gpt-…>
  tool: codex exec 0.162.1 image_generation
  date: 2026-10-14
  story: dog-weekend          # anchor group
  exif: {date: "2026-06-14T17:42:00", place: "fictional beach"}
  reviewed_by: <human name>   # a person looked at it: no faces, logos, text, artefacts
  review_date: 2026-10-14
  approved: true
```

Only `approved: true` files go into the app's screenshot scenes. Hand the manifest over with the kit.

## Other art

- **IAP promotional image:** 1024 × 1024, RGB, flattened, no rounded corners. Only needed if the IAP is promoted.
  Generate the background if you like, but compose the final image in HTML or Figma, and run it through `validate_kit.py` (`KIT/iap/<product_id>/promo.png`).
- **In-app event art:** same rules. No text baked in by the generator.
