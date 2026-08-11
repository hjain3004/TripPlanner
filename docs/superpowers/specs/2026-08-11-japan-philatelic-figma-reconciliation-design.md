# Japan philatelic frontend reconciliation

**Date:** 2026-08-11

**Status:** Human-approved design; implementation has not started

**Scope:** Documentation and delegation contract for selectively reconciling the saved Figma Make composition with the current frontend and adding one Japan-only Atlas philatelic layer

**Operating profile:** `student_noncommercial`; USD 0 additional out-of-pocket spend

**Durable visual reference:** `frontend/design/refs/philatelic/japan-atlas-stamp-concept.webp`

## 1. Authority and supersession

This document is the single entry point for this refinement. It combines two pieces of work that must not be executed independently:

1. recover the useful composition from `design/Premium Travel Itinerary Planner/` without importing its generated application; and
2. add historical postage-stamp art as a restrained Japan destination layer.

Authority order for this work:

1. product, arithmetic, evidence, provenance, and API behavior remain governed by `docs/specs/` and `AGENTS.md`;
2. `docs/superpowers/specs/2026-08-09-japan-frontend-foundation-design.md` remains the visual foundation;
3. this document governs the Figma reconciliation and philatelic addition;
4. the old `docs/superpowers/plans/2026-07-28-figma-template-reconciliation.md` is historical context only and must not be executed;
5. the saved Figma bundle is composition reference only, as stated in `design/README.md`.

Where this document is silent, preserve the current frontend and the 2026-08-09 Japan design. Do not revive Bodoni, Singapore-first styling, soft dashboard cards, the old all-ticket register, or Figma-generated component contracts.

## 2. Outcome

Refine the current frontend rather than redesigning it. Preserve the current neo-brutalist structure, Quiet Blossom palette, Poiret/Schibsted/Roboto Mono roles, typed components, fixture-backed values, and visible provenance. Recover only the strongest Figma compositions. Add a fictional historical Atlas stamp as a small collectible destination artifact that feels native to the interface.

The result must still read as a sophisticated travel optimizer for ordinary travelers. It must not become a stamp marketplace, scrapbook, postal-service simulation, or decorative tourism site.

## 3. Settled decisions

- Japan is the only destination proof in this phase.
- Neo-brutalism remains the structural base.
- Calm editorial hierarchy remains the usability layer.
- Jet-Age retrofuturism remains a restrained personality layer.
- Historical philately becomes a second restrained personality layer.
- Stamps are fictional Atlas artifacts, not authentic national postage.
- Historical intaglio/engraving is preferred over flat mid-century clipart.
- Existing CC0 archival material should be used as source/reference where suitable.
- Nano Banana Pro or an equivalent subscribed creative tool may fill composition gaps offline.
- No generator, image API, or video model is called by the product at runtime.
- The approved concept is a direction reference, not a production-ready asset.
- Creative generation and implementation are delegated. The implementing model may not reinterpret the art direction.

## 4. What the Figma bundle contributes

The folder `design/Premium Travel Itinerary Planner/` is a tracked July 2026 Figma Make export, not a new unmerged feature branch. Its six concepts already have descendants under `frontend/src/app/kitchen-sink/views/`.

Keep these composition ideas:

| View | Keep | Correct |
|---|---|---|
| Explore | Three-part destination rhythm, illustration-led discovery, clear label/title/lede hierarchy | Square ruled surfaces, restrained motion, real interaction semantics, no generic hover lift |
| Deals | Asymmetric primary story plus narrow offer/multiplier rail | Fixture-backed content, UI typography below H1, no invented live offers |
| Itinerary | Vertical journey spine, flight artifact, hotel decision ledger, rationale, nearby provenance | Current normalized components and India/Singapore data contract remain authoritative; philately appears only at the cover/issue moment |
| Proof | Source → transfer partner → redemption narrative | Rebuild from typed transfer/evidence artifacts; remove blank animation canvas and hardcoded figures |
| Wallet | Balances first, ruled perks ledger, time-sensitive opportunity rail | Preview-only until account scope permits; no bank logos, masked PAN theatre, fake synchronization, or display font on balances |
| Profile | Identity summary plus preferences/loyalty composition | Preview-only until specs 17/18; remove passport storage and unsupported security/account claims |

Do not import the Figma Vite shell, dependency manifest, generated shadcn/MUI dump, duplicate `MoneyText`, ad-hoc types, raw CSS variables, fabricated figures, or unconditional animations.

## 5. Reconciliation order

The stamp layer is not the first implementation step. It will look pasted on if the surrounding pages remain inconsistent.

### R0 — Establish the real baseline

- Start from current `main`, not the July plan's historical commit references.
- Preserve unrelated backend and itinerary work.
- Run a fresh production frontend build before bundle tests.
- Record current desktop and mobile screenshots at 390, 768, and 1440px.
- Resolve or explicitly scope the current GSAP bundle-test mismatch: the test presently scans every generated chunk while the application intentionally contains a lazy GSAP import. The gate must test the intended initial-route budget, not claim that an intentionally available lazy chunk can never exist.

### R1 — Repair composition prerequisites

- Replace the overflowing seven-item phone navigation with an accessible responsive navigation pattern.
- Ensure the preview shell uses the approved theme resolver/Japan pack rather than hardcoded `theme-singapore`.
- Remove Poiret faux-bold and Poiret leakage from H2–H6, money, points, dense cards, and navigation.
- Restore square principal surfaces, 2px ink rules, and zero-blur material offsets where the Japan contract requires them.
- Remove `transition-all`, generic hover elevation, and `scale: 0` entry motion.
- Keep rounded geometry only for genuine chips, status marks, route nodes, and the stamp's perforations/postmark.

### R2 — Reconcile product compositions

- Explore: preserve the current Japan illustrations but adopt a more disciplined ruled editorial card structure.
- Deals: retain the current asymmetric Figma-derived composition and correct typography/surface drift.
- Itinerary: preserve the current normalized implementation; polish hierarchy without changing data flow or arithmetic.
- Proof: treat the current screen as a placeholder and rebuild it only when typed transfer/evidence graph artifacts are available.
- Wallet/Profile: retain as explicitly labelled non-shipping previews until their account milestones authorize real behavior.

### R3 — Produce and approve the Japan stamp asset

- Generate alternatives outside the application using the asset pipeline in section 9.
- Human selects one composition before code integration.
- Clean, vectorize or prepare responsive raster delivery.
- Complete the source/prompt/license manifest.

### R4 — Integrate the philatelic layer

- Integrate only at the placements allowed in section 7.
- Validate the stamp in the surrounding page, never on an isolated white artboard alone.
- Keep all functional text as HTML; baked-in stamp text is decorative.
- Do not change backend schemas or result contracts for this visual layer.

### R5 — Validate and hand off

- Run accessibility, responsive, performance, token, type, unit, and screenshot gates.
- Produce a milestone report with before/after screenshots and the asset manifest.
- Do not expand beyond Japan in the same implementation cycle.

## 6. Atlas Philatelic System

### 6.1 Meaning

An Atlas stamp means **destination identity and a journey artifact**. It does not mean verified, booked, paid, transferred, legally issued, or government approved. Trust states continue to use the canonical provenance components.

### 6.2 Visual anatomy

The Japan stamp uses:

- a vertical or near-square perforated paper silhouette;
- warm rice-paper stock;
- warm sumi-brown engraving ink, never black;
- fine cross-hatching and controlled guilloche detail;
- Mount Fuji and a streamlined Shinkansen as the initial subject;
- dusty sakura as a restrained supporting pigment;
- optional tea-leaf green and tiny aged-brass details;
- a small `ATLAS` maker line;
- `JAPAN` as destination identity;
- a route/date cartouche left blank in the base artwork;
- an overlapping fictional postmark whose route and date are rendered accessibly by the product;
- a hard offset material plate when shown as a dominant artifact.

It must not include a real monetary denomination, national flag, government seal, postal-service logo, copied modern stamp, airline logo, or claim of legal postage.

### 6.3 Relationship to the existing design

- The stamp inherits Japan theme pigments; it does not introduce a new palette.
- Surrounding layout uses the existing square neo-brutalist grid.
- The stamp's perforations and circular postmark are exceptions justified by the artifact.
- Poiret remains the page display face. Engraved lettering inside artwork must not cause a second UI typography system.
- Roboto Mono may label the airport pair/date outside or alongside the artwork.
- Philatelic material should occupy roughly 10–15% of a representative screen, not dominate every viewport.

## 7. Placement contract

### Allowed

1. One destination artifact in the landing or Japan discovery hero.
2. A smaller Japan stamp thumbnail on a destination-selection or Explore surface.
3. One itinerary-cover/plan-issued moment after a successful result is available.
4. A saved-trip collection in the future, after persistence exists.
5. A quiet loading placeholder or reveal, provided it does not imply progress percentage.
6. A decorative postmark beside a genuine itinerary date/route when the route/date are supplied by the report and remain readable as HTML.

### Forbidden

- Ordinary buttons, inputs, dialogs, navigation tabs, or every card.
- Hotel comparisons, payment strategy, money, points, transfers, ledgers, or provenance bands.
- Trust chips or any state where a stamp could be mistaken for verification.
- Error, warning, or stale-data status.
- Bank/card identity, account balances, offers, or issuer branding.
- Repeating stamp wallpaper, scattered sticker collage, or scrapbook decoration.
- Runtime personalization that generates new art per user.

## 8. Motion contract

The artifact may have one rare plan-issued reveal:

1. stamp settles by at most 8px over 450–650ms;
2. hard offset aligns slightly as it settles;
3. postmark appears with opacity plus a restrained `0.97 → 1` scale;
4. no bounce, spinning, confetti, ink splash, or `scale: 0`;
5. reduced motion renders the final state immediately or with opacity only.

This motion is implemented in CSS/WAAPI or the existing lightweight motion layer. Veo/Flow may be used to explore motion references, but generated video must not ship in the interface.

## 9. Delegated asset pipeline

### 9.1 Source discovery

Prefer assets carrying an explicit CC0/Public Domain designation from:

- Smithsonian Open Access / National Postal Museum: `https://www.si.edu/openaccess`
- Library of Congress Free to Use and Reuse travel material: `https://www.loc.gov/free-to-use/`
- The Metropolitan Museum of Art Open Access collection: `https://www.metmuseum.org/art/collection`
- Openclipart CC0 vectors: `https://openclipart.org/faq`

Search engines and aggregators are discovery tools, never the license authority. Record and inspect the original item page. Do not use an item whose media rights are ambiguous, even when its metadata is open.

### 9.2 Creative generation

Use the human's existing Google AI Pro subscription manually. Do not add a Gemini key, API client, MCP, or recurring cost to the repository. Do not buy top-up credits for this task.

Generate two production candidates from one locked brief, using the approved concept as the direction reference. Change composition only; do not change palette, semantics, or style between candidates. Keep all source URLs and generation prompts.

#### Locked Nano Banana master prompt

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

The generated words are references, not authoritative UI text. Correct `ATLAS`/`JAPAN` during cleanup. Route/date/year always render outside the base image from report data; never manufacture them for visual effect.

### 9.3 Cleanup and delivery

- Prefer a manually cleaned SVG when the trace remains efficient.
- Inkscape Trace Bitmap, SVGcode, or VTracer may create a starting point; a raw automatic trace is not final.
- Remove excess nodes, embedded rasters, metadata bloat, scripts, event handlers, external URLs, fonts, and `foreignObject`.
- Use semantic/currentColor integration only where it does not destroy the approved multi-ink art. Otherwise export destination-specific static art.
- If engraving density makes SVG excessive, deliver responsive WebP/AVIF instead of forcing a multi-megabyte vector.
- Production target: optimized SVG no larger than 200 KB, or largest responsive raster no larger than 160 KB. Initial-route philatelic payload must remain under 250 KB.
- Preserve the high-resolution creative source outside the runtime asset path.
- The approved concept reference is exempt from runtime budgets because it is not imported by the application.
- If the generation surface adds a visible provider watermark, do not crop, paint over, or remove it. Use that output only as a composition reference and rebuild the production asset from reviewed CC0 sources and original vector work.

Suggested paths:

```text
frontend/design/refs/philatelic/              # approved concept/reference
frontend/public/img/japan/philatelic/         # production assets only
frontend/public/img/japan/philatelic/MANIFEST.md
```

### 9.4 Manifest fields

For every source and output, record:

```text
asset_id
output_path
source_item_url
source_creator
source_rights_statement
source_download_date
source_crop_or_transformation
generator_product_and_model
generation_date
exact_prompt
human_selected_revision
vectorizer_or_cleanup_tool
final_format_and_bytes
intended_placements
```

Google does not claim ownership over original generated output, but that does not guarantee non-infringement. Avoid named living artists, recognizable protected characters, trademarks, and modern stamp imitation.

## 10. Component boundary

If implementation needs a component, use one small, typed presentation component such as `DestinationStamp`. It receives an approved static asset and accessible metadata. It does not fetch, generate, choose themes, compute routes, or infer countries.

Conceptual contract:

```ts
type DestinationStampProps = {
  asset: ApprovedPhilatelicAsset;
  size: "thumbnail" | "feature";
  decorative?: boolean;
  routeLabel?: string;
  dateLabel?: string;
};
```

The actual type should reuse an existing asset/fixture type where possible. Do not create an ad-hoc data model merely to match this pseudocode. If `decorative` is false, provide concise alternative text. If true, use empty alternative text and `aria-hidden` where appropriate.

## 11. Accessibility and content safety

- No essential destination, date, airport, itinerary, or status information exists only inside the image.
- Decorative stamp text is not announced twice.
- Meaning is never conveyed solely by pigment.
- Postmarks may not obscure functional labels or targets.
- The artifact retains readable contrast against Japan background and surface tokens.
- At 200% zoom, the artwork may crop responsively but page content must not overlap.
- Reduced-motion behavior follows section 8.
- Generated artwork is visually reviewed for malformed text, accidental symbols, logos, faces, stereotypes, and culturally reductive imagery.
- Japan avoids flag clichés, anime styling, geisha/samurai tropes, and scattered-petal wallpaper.

## 12. Delegation protocol

### Creative-tool task

The creative operator uses Nano Banana Pro only to produce two candidates from the locked brief. They do not redesign pages or invent product data. Deliverables are the candidates, exact prompts, generation metadata, and source links.

### Asset-cleanup task

The cleanup operator selects the human-approved candidate, creates the optimized production asset, sanitizes it, and completes the manifest. They do not change composition without human approval.

### Frontend implementation task

The implementation model must begin by reading `AGENTS.md`, this document, and the 2026-08-09 Japan design. It should invoke available equivalents of:

- `superpowers:using-superpowers`
- `superpowers:test-driven-development`
- `superpowers:verification-before-completion`
- `superpowers:requesting-code-review`
- `frontend-design:frontend-design`
- `emil-design-eng`
- `design:accessibility-review`
- `design:design-system-management`

It must not use Figma Make, a component registry, or an image generator as authority over this spec. Registry code is reviewed and retokenized before commit. Implementation uses small commits, leaves backend behavior untouched, and logs judgment calls.

## 13. Verification gate

The work is complete only when all applicable checks pass:

1. fresh production build;
2. TypeScript strict check;
3. token lint with zero unexplained violations;
4. frontend unit/contract tests, including no orphan money/points;
5. responsive screenshots at 390, 768, and 1440px for landing/Explore/itinerary placements;
6. keyboard and focus-visible review;
7. reduced-motion screenshot or assertion;
8. no horizontal navigation overflow at 390px;
9. no Poiret below its allowed display role and no faux-bold Poiret;
10. no `transition-all` or `scale: 0` in the touched experience;
11. manifest present and every production asset traceable to source/prompt;
12. production asset/payload budgets pass;
13. no scripts, event handlers, external fetches, or unsafe SVG features;
14. no new runtime generator/API dependency;
15. human screenshot review confirms the stamp feels integrated rather than pasted on.

## 14. Non-goals

- No India, Singapore, UAE, USA, Europe, or worldwide stamp packs.
- No stamp collection database or gamification.
- No user-generated stamp artwork.
- No dynamic AI imagery.
- No authentic postage reproduction or government branding.
- No shipping video background or autoplay media.
- No backend, optimizer, evidence, provider, MCP, account, or API-contract changes.
- No promotion of Wallet/Profile from preview to implemented account features.
- No wholesale import of the Figma project.

## 15. Definition of success

A normal traveler experiences the same calm, rigorous planner. The Figma-derived pages regain clear editorial composition and neo-brutalist discipline. The Japan stamp creates one memorable, collectible moment and reinforces destination identity without competing with itinerary decisions, financial analysis, or provenance. Another model can execute the work without choosing a new theme, generating unsupported data, or guessing where stamps belong.
