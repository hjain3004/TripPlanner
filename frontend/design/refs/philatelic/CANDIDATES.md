# Japan Atlas stamp candidates

Task: `docs/superpowers/plans/2026-08-11-japan-philatelic-frontend-reconciliation.md` Task 7.

Generation date: 2026-08-12

Status: Candidate A selected by human on 2026-08-12. These files are reference candidates only. They are not runtime assets, not approved production art, and not integrated into product code.

## Source direction reference

- Reference image: `frontend/design/refs/philatelic/japan-atlas-stamp-concept.webp`
- Reference role: direction reference for composition, material feel, and philatelic framing.
- Review note: the reference concept itself is not compliant as a final asset because it bakes in `2026` and `DEL/HND`.

## Locked prompt

```text
Create one fictional ATLAS collectible travel stamp for a Japan itinerary.

Historical intaglio engraving: fine cross-hatching, controlled guilloche detail,
subtle printing irregularity, authentic perforated rice-paper edges. Show Mount Fuji
with a streamlined Shinkansen below. Use warm sumi-brown instead of black, dusty
sakura, muted tea-leaf green, and tiny aged-brass details. Low chroma, natural,
light, tactile, and ultra-premium.

Sparse text only: ATLAS and JAPAN. Leave one small route/date cartouche blank so the
product can overlay itinerary-derived airport codes and dates as accessible HTML. Add a
restrained fictional circular journey postmark that overlaps one edge, but do not bake a
route, date, or year into it. The stamp is a private Atlas travel artifact, not legal postage.

No real denomination, flag, government seal, postal-service logo, airline logo,
copyrighted character, copied modern stamp, neon, glow, glossy 3D, scrapbook styling,
hands, fake/decorative watermark, or black ink. Leave enough negative space that the design remains
legible when displayed at 180–260 CSS pixels.
```

## Candidate A

- File: `frontend/design/refs/philatelic/candidates/japan-atlas-stamp-a.webp`
- Selection status: selected as the visual direction.
- Product/model name shown by tool: Codex built-in `image_gen` tool; underlying model name was not exposed in tool output.
- Input/reference image used: yes, `frontend/design/refs/philatelic/japan-atlas-stamp-concept.webp`.
- Local high-resolution source location: `/Users/himanshu_jain/.codex/generated_images/019f94fb-42c9-7d80-a5a6-2565507c8114/call_2D9PRQ73OKuXU1iMesioRGux.png`
- Visible watermark status: no visible watermark observed.
- Malformed text/logos/symbols noticed: `ATLAS` and `JAPAN` are readable; no route, date, year, denomination, flag, postal-service logo, airline logo, government seal, or copied character observed. The postmark repeats `ATLAS`/`JAPAN`, which remains within the sparse-text rule but should be reviewed at small size.
- Safety/cultural review: no anime/geisha/samurai cliché observed; Mount Fuji, Shinkansen, sakura, and engraving style are consistent with the approved brief.
- Intended cleanup path: if selected, use this only as a layout/color reference. Rebuild or manually clean for Task 8, remove any raster artifacts, correct text if necessary, and output an optimized reviewed SVG/WebP/AVIF runtime asset with a manifest.

## Candidate B

- File: `frontend/design/refs/philatelic/candidates/japan-atlas-stamp-b.webp`
- Selection status: rejected as the production direction.
- Product/model name shown by tool: Codex built-in `image_gen` tool; underlying model name was not exposed in tool output.
- Input/reference image used: yes, `frontend/design/refs/philatelic/japan-atlas-stamp-concept.webp`.
- Local high-resolution source location: `/Users/himanshu_jain/.codex/generated_images/019f94fb-42c9-7d80-a5a6-2565507c8114/call_EA609RWpevaUFD6ggywEjA0P.png`
- Visible watermark status: no visible watermark observed.
- Malformed text/logos/symbols noticed: `ATLAS` and `JAPAN` are readable; no route, date, year, denomination, flag, postal-service logo, airline logo, government seal, or copied character observed. The blank cartouche sits high in the composition and needs product-context review before selection.
- Safety/cultural review: no anime/geisha/samurai cliché observed; Mount Fuji, Shinkansen, sakura, and engraving style are consistent with the approved brief.
- Intended cleanup path: if selected, use this only as a layout/color reference. Rebuild or manually clean for Task 8, remove any raster artifacts, correct text if necessary, and output an optimized reviewed SVG/WebP/AVIF runtime asset with a manifest.

## Process note

The implementation plan names manual Google AI Pro / Nano Banana generation. In this Codex session, the available generation path was the built-in `image_gen` tool, which did not add a repository API key, MCP, paid service, or recurring cost. If the project requires strict Nano Banana provenance, reject both candidates and regenerate manually outside Codex before continuing Task 8.

Human follow-up on 2026-08-12: do not generate more stamp/postmark imagery. Use Candidate A as the selected direction and complete the runtime asset/component/integration work through cleanup, code, layout, and tests.
