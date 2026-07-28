# Plate & Proof — frontend visual direction

**Date:** 2026-07-28
**Status:** PAUSED — direction decided, partially proven, **not approved for implementation**.
**Owner decision:** frontend work stopped here; focus moved to backend.

Read this before touching frontend visuals again. It is written to be self-sufficient
from a cold start — you should not need to re-derive any of it or re-run the probes.

---

## 1. Why this exists

The F1.5 landing page shipped matching its approved *composition* but reading pale and
generic. A session was spent diagnosing that, and it turned out to be two separate
problems that had been conflated:

- **Risk A — the design was never right.** Partly true, but narrower than assumed.
- **Risk B — the design was right and the build diverged.** This is what actually
  happened in F1–F1.5, and no preview process fixes it. Only a visual-diff gate does.

The user reopened the visual direction (Tier-F scope: `CONTRACT.md`, specs 10/11, token
layer). This document records what came out of that.

## 2. The direction

**Plate & Proof.** A premium travel field guide whose graphics explain themselves.
Two registers, one palette:

- **Plate** — the destination. Real photographs, posterized and vectorized into flat
  editorial illustration. Carries atmosphere.
- **Proof** — the argument. Hand-authored line diagrams: route line, points transfer
  graph, cost decomposition, offer stack, provenance trail. Carries explanation.

**Motion references:** 3Blue1Brown and Vox. Both share one rule and it is already the
product's rule — *motion is the argument, never decoration*. This aligns with
non-negotiable #3 in `CLAUDE.md` (every fact carries provenance).

**Ground:** paper throughout. Dark "explanatory stage" panels were proposed and
**rejected** by the user. Distinctiveness must therefore come from illustration and
from display type at real weight — not from ground inversion.

## 3. What survives vs what was reopened

| Survives untouched | Reopened |
|---|---|
| Composition, grid, split hero, wayfinding spine, ledger geometry | Display colour role and weight floor |
| Bodoni Moda / Schibsted Grotesk / Roboto Mono assignment | Palette **role** system (values unchanged) |
| "Display in hero/h1/h2 only" rule (`CONTRACT.md` §1) | Illustration system (new — did not exist) |
| All `singapore.css` token **values** | Motion vocabulary |
| G1 dead-class gate, G2 screenshot gate | `CONTRACT.md`, specs 10/11 |
| Entire backend | |

The reopen is **narrower than "reopen the visual direction"** implies. The geometry was
never the problem.

## 4. PROVEN — safe to build on

### 4.1 The display fix (this was the actual root cause)

The shipped hero rendered Bodoni Moda at **weight 400 in celadon**. `singapore.css`
already contains a correct ink (`--th-text: oklch(0.281 0.007 145)`) that display type
simply never used, so it inherited an accent. That is why the page read as absence.

**Rules to write into `CONTRACT.md`:**

- Display colour defaults to `ink`. Non-negotiable.
- **Display weight floor: 600.** A floor, not a default. Bodoni Moda's variable axis
  reaches 900. At 92px/600 you get thick stems against hairline contrast — the engraved
  plate look that pairs with the illustration.
- Exactly **one** display line per page may take `signal` as deliberate emphasis.
- Making these contract rules turns the previous failure state into a lint violation
  rather than a judgment call.

Verified visually in `frontend/design/probes/plate-and-proof-still.html` (side-by-side
A/B at the foot of the page). The difference is not marginal.

### 4.2 Palette roles — reassignment only, zero new token values

The bug was structural: display type had no ink role. Roles fix it.

| Role | Token | Job |
|---|---|---|
| `paper` | `--th-bg` / `--th-surface` | ground |
| `ink` | `--th-text` | **all display**, body |
| `structure` | `--th-primary` (mangrove) | rules, nodes, every drawn line |
| `signal` | `--th-accent-4` (lacquer) | the one thing currently being explained |
| `value` | `--th-accent-3` (brass) | money saved, only |

`signal` is the new concept and it is what makes the explanatory register legible.
**Nothing is `signal` at rest.** Lacquer's existing <2% surface budget is exactly the
right constraint for "one thing at a time."

### 4.3 The proof register works

Route diagram with mono labels, `structure` line, `signal` terminal node reads as
explanatory rather than decorative. Same palette as the plates is what makes the page
one system instead of art-plus-charts.

### 4.4 The plate technique and the palette-unity mechanism

`frontend/design/pipeline/posterize.py` maps photo luminance onto a fixed ramp derived
from the OKLCH tokens. Verified: it converts to `#FAF8F2`, `#DBE7E0`, `#BDD3C9`,
`#173A34` — matching `singapore.css` **verbatim**, so the OKLCH→sRGB math is correct.

**This is the load-bearing idea.** Palette unity is guaranteed *by construction*: any
photograph in, the same five colours out. Six plates from six unrelated sources cohere
automatically. This is the property that hand-drawing and naive tracing both failed to
provide.

Best result so far: `--levels 5 --smooth 11` on a tightly cropped source
(`frontend/design/probes/taj-post.png`). Flat, graphic, screenprint-like, clearly the
Taj Mahal, clearly not a photograph.

## 5. REJECTED — do not revisit

- **Hand-authored geometric line art.** Built and tested. Marina Bay Sands in true
  orthographic elevation is genuinely three posts under a plank — its recognizability
  lives entirely in the three-quarter view. More importantly, this was a **misreading of
  the brief**: the user wants photographs run through a vectorize filter, still looking
  like the actual thing, not drawings. See `probes/plate-v2-1440.png`.
- **Raw `image_vectorize` on an unprocessed photo.** Produces a high-fidelity trace
  *with gradients*: 2.5 MB, 4,181 paths, muddy source colours, no palette relationship.
  It timed out a headless browser at 30s. Six of these would fail the F4 performance
  gate outright. Posterization must happen **before** the trace, never after.
- **Dark ground / dark explanatory stages.** Explicitly rejected by the user.
- **`--levels 4`.** Overshoots: dome fragments, sky blotches. See `taj-post2.png`.

## 6. NOT PROVEN — the open risks

1. **Threshold strategy is wrong for high-key subjects.** `posterize.py` uses quantile
   thresholds, which force an even pixel distribution across bands. A monument against
   bright sky is bimodal, so 25% of pixels get dragged into the darkest band — sky
   blotches, dome splits. **Fix:** add a `--bias` parameter shifting thresholds off the
   quantiles, or support fixed per-source thresholds. Small change, not yet made.
2. **The vectorize step has never been run on posterized input.** Path count and file
   size are *expected* to collapse once the input is 4–5 flat colours with smooth edges,
   but this is **unverified**. It is the one remaining risk to the F4 performance gate.
   Do not treat it as settled.
3. **Motion on plates.** Traced fills cannot do 3B1B stroke-draw — there is no stroke.
   Proposed replacement is **tonal build**: reveal the posterized colour layers in tone
   order so the image assembles out of its own shadows. Untested. Diagrams keep full
   draw-on since they stay hand-authored line work.

## 7. Constraints carried forward

- **Licensing.** Every Wikimedia Commons candidate is CC BY-SA — share-alike with
  **mandatory attribution**. Workable for a student project and it fits the provenance
  model, but it needs a `DEVIATIONS.md` entry and an attribution surface in the UI.
  Source photos must be curated: clean, isolated subject, tight crop. Source framing
  dominated every parameter tuned.
- **Adobe account.** `get_account_type` returns `auth`. The user authorised use of the
  Adobe MCP for `image_vectorize`. Generative AI is **not** available on this connector;
  it is not needed. Requires a `DEVIATIONS.md` entry (paid service, per the ambiguity
  protocol) — **not yet written**.
- **`image_vectorize` domain allowlist.** It rejects `upload.wikimedia.org`. Sources must
  be uploaded to Adobe storage first (`asset_initialize_file_upload` → chunk PUT →
  `asset_finalize_file_upload`) and referenced by the returned `presignedAssetUrl`.
  Large/complex sources return HTTP 504; downscale first.

## 8. The gate that actually matters

F1.5 diverged because **nothing compared the built app to the approved reference**. G1
catches invisible text, G2 catches broken responsive; neither catches "it just doesn't
look like it."

**Propose G3: visual diff of the built page against the approved artifact.** This
addresses Risk B, which no amount of design preview can. If only one thing from this
document gets implemented, it should be this.

## 9. Tooling decision

Build the direction as a **self-contained animated HTML artifact in-repo**, not Figma.
Stroke-draw and morph transitions can only be judged in motion, and the approved SVG
paths and CSS custom properties become literally the same ones in the Next.js app — no
translation layer, which is where the drift came from.

Figma has **no built-in Image Trace**; that is an Illustrator feature. Adobe MCP's
`image_vectorize` is the same engine and is the chosen production path.

## 10. Artifacts on disk (all untracked, nothing committed)

```
frontend/design/pipeline/posterize.py          the pipeline — works, needs --bias
frontend/design/probes/plate-and-proof-still.html   type + palette + diagram probe
frontend/design/probes/plate-and-proof-still-1440.png
frontend/design/probes/plate-v2-1440.png       rejected hand-drawn line art
frontend/design/probes/taj-post.png            BEST — 5 levels, smooth 11
frontend/design/probes/taj-post2.png           overshot — 4 levels
frontend/design/probes/mbs-traced.svg          2.5 MB — evidence only, DO NOT COMMIT
frontend/design/probes/mbs-*.jpg               sources
```

## 11. When frontend resumes, start here

1. Add `--bias` to `posterize.py`; re-tune the Taj plate to beat `taj-post.png`.
2. Run the posterized PNG through `image_vectorize`; confirm path count and file size
   collapse. **If they don't, the whole plate approach needs rethinking** — deliver SVG
   only if it's small, otherwise export WebP.
3. Only then write the implementation plan and revise `CONTRACT.md` + specs 10/11.
4. Write the two outstanding `DEVIATIONS.md` entries (Adobe paid service; CC BY-SA
   attribution obligation).
5. Update the `CLAUDE.md` "Current checkpoint" section, which still describes the
   superseded Bodoni-at-400 state.

**Do not** write the contract revision before step 2 passes. Writing an illustration
spec before the pipeline was proven is exactly what produced the last handoff that
didn't survive contact with implementation.
