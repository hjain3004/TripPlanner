# Handoff — TripPlanner frontend type & register work

**From:** session of 2026-08-08 (context exhausted, ~$98 spend)
**For:** the next session, continuing frontend visual direction
**Repo:** `/Users/himanshu_jain/TripPlanner`, branch `main`

---

## 0. Read first, in this order

1. `CLAUDE.md` — agent brief. Five non-negotiables, decision tiers, ambiguity protocol.
2. **`docs/superpowers/plans/2026-08-08-jet-age-issue-register.md`** — the primary artifact from
   that session. Self-sufficient from a cold start. **§11 is the live state**; read it before §3,
   because §3's font token is stale.
3. `frontend/design/CONTRACT.md` §1–3 — the frozen contract this work amends.

Do **not** re-read the 17 specs in `docs/specs/`. Do not re-derive the visual direction — four
rounds of probing already happened and the rejections are recorded.

---

## 1. One-paragraph state

The backend is done for its scope (133 tests, `mypy --strict` clean on 42 production files) and is
**not** what this work touches. The frontend has a complete, gated F1–F4 build whose visual system
is *calm editorial* — and the human wants neo-brutalist / retro-futurist. The root cause was
diagnosed: five neo-brutalist mechanics (0 radius, hard offset shadow, thick borders, grotesque
display, saturation) are each forbidden at the token layer and frozen Tier-F in `CONTRACT.md`, so
the direction could never render regardless of implementation quality. The fix is a **two-register
system** — calm shell, hard "issued document" for anything showing a kernel-computed number.
Geometry is approved. Type is nearly settled. Nothing is committed.

---

## 2. Settled — do not reopen

- **Geometry (Direction A):** 0 radius, 2px rules, 12px offset plate, mono metadata, split-flap for
  the money moment. Approved on a rendered 1440px comparison.
- **Register boundary rule:** *a surface enters the issue register if and only if it renders a
  number the deterministic kernel computed.* Component lists are in the plan §2.
- **Synthwave / neon / CRT retro-futurism: rejected outright.** Human's words: *"absolutely
  terrible and i don't want anything even remotely resembling this."* Never resurface it.
- **Light ground stays.** An earlier note in plan §11 suggesting the system go dark-first was
  **wrong** and the human corrected it: *"no i dont want light on dark... dont change the color
  scheme."* The singapore palette is unchanged — limestone, paper, mangrove, celadon, brass,
  lacquer. **Fix this in plan §11; it is the one known-stale statement in the plan.**
- **Rejected type, with reasons on record:** Bodoni Moda 400 and 600, Instrument Serif, Fraunces
  600, Space Grotesk 700, Abril Fatface, Alfa Slab One, Pirata One (blackletter), Monoton,
  Josefin Sans, Julius Sans One, Limelight.

---

## 3. Chosen — Poiret One, with a role map

The human supplied two reference images (`frontend/design/refs/font-decision/Screenshot 2026-08-08
at 1.14.59 PM.png` and `...1.18.41 PM.png`) — Art Deco / Streamline Moderne titling. They chose
**Poiret One**. Proposed role map, rendered in `frontend/design/probes/poiret-roles-1440.html`:

| Role | Face | Constraint |
|---|---|---|
| Display — hero, h1, h2 | **Poiret One** | Caps, tracked +0.09em, never below 40px |
| Script — eyebrow only | **OPEN** — Parisienne / Petit Formal Script / Yellowtail | Eyebrows and kickers only; never a heading, body, or number |
| UI — h3 down, body, money | Schibsted Grotesk *(unchanged)* | All monetary values, tabular-nums mandatory |
| Mono — data, codes | Roboto Mono *(unchanged)* | Datelines, airport codes, provenance, split-flap |

Poiret One replaces **Bodoni only** — the same three contexts (hero/h1/h2). `CONTRACT.md`'s
existing display-leakage guard carries over with the face name swapped.

---

## 4. Open — start here

### 4.1 The immediate blocker: Poiret One stroke weight

The human's last instruction: *"thickness is too less. probably increase thickness by 50% or
something, since its a heading."*

**Poiret One is a single-weight family. `font-weight` cannot thicken it** — a bold request yields
browser faux-bold, which smears hairline deco joins. Options presented, none yet chosen:

1. `-webkit-text-stroke: 1.2px currentColor` + `paint-order: stroke fill` — preserves Poiret One's
   letterforms, thickens strokes. **Recommended.** Needs a render at 1.0 / 1.2 / 1.5px to tune;
   check the joins on `R` and `G`.
2. Swap to a deco face with real weights — only Josefin Sans qualifies, already rejected.
3. Keep it thin, gain presence from scale and tracking instead (traditional deco practice).

**First action for the next session: render option 1 at three stroke widths and let the human pick.**

### 4.2 Script eyebrow — three candidates rendered, none chosen

Bottom row of `poiret-roles-1440.html`. Note raised and unresolved: a script face is the easiest
way to make a UI look cheap; dropping the script entirely and using Roboto Mono for eyebrows is a
defensible lower-risk option.

### 4.3 Then, and only then

Update plan §3 (font tokens) and §4 (work order) to match, plus the `CONTRACT.md` §1–2 face swap.
Plan §4 must **not** be executed until §11 is closed out.

---

## 5. Files

**Probes** — all standalone, none shipped, all in `frontend/design/probes/` with matching `.png`:

| File | Verdict |
|---|---|
| `three-directions-1440.html` | Geometry — **A won**, B rejected outright, C's plate fix validated |
| `display-font-1440.html` | Serifs — all rejected |
| `gazette-1440.html` | Mastheads — all rejected |
| `deco-1440.html` | Deco faces — **Poiret One chosen** |
| `poiret-roles-1440.html` | Role map — **script slot still open** |

**Superseded — do not execute:** `frontend/PROBE_REV2_HANDOFF_PROMPT.md`. The plan instructs
deleting it.

**Rendering probes:** the Browser pane proved unreliable (hung on scroll). What worked: write a
throwaway `.probe-shot.mjs` **inside `frontend/`** (so `@playwright/test` resolves), launch
chromium at 1440×1200 `deviceScaleFactor: 2`, `waitForTimeout(2500)` for webfonts, screenshot
`fullPage`, then delete the script.

**Git:** nothing committed. Untracked: 5 probe HTML + 8 PNG, the plan, and the two reference
screenshots. **Commit these early next session** so the rejected directions stay on record.

---

## 6. Corrections to inherited docs

- `CLAUDE.md` says the backend regression floor is 97/100 tests. **It is 133.** Verified 2026-08-08.
- `CLAUDE.md` says "There is no provider gateway." **Stale** — `backend/gateway/evidence/` exists
  with 8 tested modules.
- Plan §11's dark-ground paragraph is wrong (see §2 above).

---

## 7. Suggested skills

- **`superpowers:executing-plans`** — before touching code; the plan has checkpoints at steps 2/3/5.
- **`superpowers:verification-before-completion`** — before claiming any gate passes.
- **`ui-ux-pro-max:ui-ux-pro-max`** — contrast/motion lookups (`--domain ux`, `--domain color`).
  Caution: its style DB returns *synthwave* for "retro-futurism," which is rejected here.
- **`superpowers:systematic-debugging`** — if the plan's §3 `@theme inline` bridge change moves
  anything visually. Precedent exists for silent Turbopack utility-generation failures.
- **Do NOT invoke `superpowers:brainstorming`** — direction is decided and rendered.

---

## 8. Working notes

- **A GateGuard hook fires before every first Bash/Write/Edit**, demanding importers, affected API,
  data schemas, and the user's verbatim instruction. It fired 9 times last session. State the four
  facts concisely and retry the identical call. `ECC_GATEGUARD=off` disables it.
- **Method that works here: build a probe and look at it.** The human judges visually and has
  overruled type proposals three times. **Ask for references before proposing type.** Prose
  descriptions of fonts were consistently wrong; rendered comparisons were consistently right.
- **Cost discipline:** last session hit ~$98, largely on probe iteration. Each probe render plus
  image read is expensive. Batch candidates into one probe rather than iterating one face at a time.
