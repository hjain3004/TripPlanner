# Handoff — Issue Register probe, revision 2

**Status:** ready to execute. Design-only. The frontend remains paused.
**Written:** 2026-07-29, after a side-by-side review of the rev-1 probe against the running app.

---

## 0. Read these first, in this order

1. `CLAUDE.md` — the agent brief. The five non-negotiables and the ambiguity protocol bind you.
2. `docs/superpowers/specs/2026-07-29-visual-system-reconciled.md` — the authoritative visual spec you are testing.
3. `docs/superpowers/plans/2026-07-29-visual-system-reconciliation.md` — the plan that produced rev 1. Its §4A lists the acceptance criteria, its §6 lists what is out of scope, its §7 records the two known risks.
4. `frontend/design/CONTRACT.md` — the frozen F1 implementation contract.
5. `frontend/design/probes/issue-register-1440.html` — the artifact you are revising.
6. `frontend/design/probes/plate-and-proof-still.html` — the earlier direction, kept for comparison.

Do **not** re-read the 17 specs in `docs/specs/`. Do not reopen settled decisions; §2 of the spec lists the conflict resolutions that are closed.

---

## 1. Why this revision exists

Rev 1 was reviewed at 1440px next to the running app (`npm run dev`, landing page at `/`). The plan's §7 named the risk precisely:

> The probe is the real test. Whether "calm neobrutalism" reads as *calm* rather than merely quiet is only answerable by looking at it. **If the probe fails that comparison, the spec changes, not the probe.**

It failed. It reads as quiet, not calm. Five defects, below. Your job is to fix them and re-render so a human can judge the direction properly.

**This is aesthetic work, not mechanical work.** You are being asked to make a design read correctly, not to satisfy a checklist. If a fix below makes the probe worse, say so in your report rather than shipping it.

---

## 2. The five defects

### D1 — the offset plate is too small and too low-contrast to register (primary)

`issue-register-1440.html:63`:

```css
.document::before {
  content: ""; position: absolute;
  top: 6px; left: 6px; right: -6px; bottom: -6px;
  background: var(--celadon-1); z-index: -1;
}
```

The geometry is **correct** — this is a true +6/+6 offset with no blur, exactly as the spec §4 describes. The problem is that a 6px band of `celadon-1` (`oklch(0.848 0.027 167)`) against `paper` (`oklch(0.979 0.008 91)`) does not read as a second printing plate. At normal viewing distance it reads as a soft drop shadow — precisely the treatment the spec claims to be replacing. The 2px mangrove rule is carrying all the visual weight; the celadon is carrying none.

**Fix:** raise the offset until the plate reads as a deliberate second impression. Start at 10px and 12px and look at both. Keep `celadon-1`.

**Do not substitute mangrove/`--structure` for the plate colour.** The register system (spec §3) assigns celadon to `issue` and mangrove to `structure`; recolouring the plate collapses two registers into one and destroys the meaning system. If after trying 10px and 12px you still believe celadon cannot carry it, **stop and report that** — it is a spec change, requiring a `DEVIATIONS.md` entry and a human decision, not something you resolve yourself.

Update spec §4's `+6px/+6px` to whatever value you land on, in the same commit.

### D2 — the probe never tests the actual thesis

Plan §4A requires the documents be shown *"against the calm shell for contrast."* Rev 1 has no shell — the documents float on bare `--paper-deep`. The entire spec is the claim "calm shell, issued documents," and rev 1 cannot answer whether that pairing works because half the pairing is absent.

**Fix:** add a band of the real shell treatment to the probe, adjacent to the documents. Source it from the running landing page (`frontend/src/app/page.tsx` and the components it pulls from `src/components/product/`) — the Bodoni Moda display heading, the celadon grid panel, the mono metadata labels, the 12px-radius soft-shadow surfaces. Reproduce it in the probe's standalone-HTML idiom; do **not** import from `src/`.

The judgement the probe must enable: *do the documents read as issued objects sitting inside a calm environment, or do they read as a second unrelated design language?*

### D3 — the `stale` plate is invisible, conflating `stale` with `estimated`

```css
.document.stale::before { background: var(--rule); }
```

`--rule` is `oklch(0.28 0.01 145 / 0.10)` — a 10%-alpha hairline colour. As a plate fill it is effectively transparent. Spec §4 says `stale` is *"plate greyed"* and `estimated` is *"no offset plate — nothing was issued."* Right now both render with no visible plate, so the one dimension that distinguishes them does no work.

**Fix:** give `stale` a genuinely greyed but visible plate. Use an existing palette value at full opacity (`--ink-faint` is the obvious candidate; `--paper-deep` is likely too close to the background). `estimated` keeps `display: none` — that is correct and deliberate.

### D4 — the `verify_required` stamp collides with the `DESTINATION` label

`.stamp-verify` is `position: absolute; top: 16px; right: 16px;` and lands directly on top of the `DESTINATION` field label. Both strings overprint and both become unreadable.

**Fix:** reposition or reserve space. A real stamp lands in margin or dead space, not across a data field. Note that `verify_required` is the one place lacquer is mandatory (spec §2, last row) — the stamp must stay prominent, so solve this with layout, not by shrinking it.

### D5 — left-in reasoning comments in the committed source

Lines 124–125 contain an LLM thinking out loud:

```
/* Re-reading rules: use --rule or --ink-faint or similar existing color for greyed.
   Let's use --rule for the plate background if it's greyed, or just --paper-deep, or
   something muted. Actually, --ink-faint is greyish. Or maybe --ink-faint for the
   background is too dark? --rule is light grey (...). */
```

**Fix:** delete. Replace with a one-line comment stating the decision, if a comment is warranted at all. Sweep the file for others.

---

## 3. Also missing

Plan §4A requires *"a transfer-plan stub with perforation"* as one of the five things the probe must show. The `.stub` class exists (`border-top: 2px dotted var(--structure)`) but is only used inside the `verify_required` card. Add the transfer-plan stub as its own specimen — a detachable stub below a document, per spec §4's graph-concepts table.

While you are there, check the `CONTRADICTS` specimen. The intent (spec §4) is *"two plates visibly out of register — double-vision offset."* As rendered, the specimen's content sits on a solid celadon field while every other document's content sits on paper, so it reads as "highlighted" rather than "misregistered." Make the misregistration the thing that communicates, not the fill.

---

## 4. Hard constraints

- **Introduce no new colour value.** Not one new hex, not one new OKLCH. The eleven values in the probe's `:root` are lifted verbatim from `frontend/src/themes/singapore.css` and that comment convention must survive. Same for fonts: Bodoni Moda, Schibsted Grotesk, Roboto Mono, nothing else.
- **`frontend/src/` is untouched.** Zero files modified under it. The frontend is paused; this is a design probe. (You will *read* `src/` for D2 — reading is fine, importing and editing are not.)
- **No `backend/` changes. No `docs/specs/` changes** — that directory is read-only during implementation.
- **Do not push, do not merge, do not open a PR.** Leave the branch local and report.
- Bodoni Moda appears on the calm shell only, **never inside a document** (spec §4).
- Lacquer stays under its <2% surface budget and stays mandatory on exactly one thing: `verify_required`.
- If a spec §2 decision looks wrong, implement it as written, log the objection in `DEVIATIONS.md`, and raise it in your report. Do not silently deviate.

---

## 5. Branch, and what to write

Branch `docs/visual-system-probe-rev2`, off `main` (currently `deecb96`). The working tree is clean and `npx tsc --noEmit` in `frontend/` exits 0 — keep both true.

**Files you will touch:**

| File | Change |
|---|---|
| `frontend/design/probes/issue-register-1440.html` | D1–D5 plus §3 additions |
| `docs/superpowers/specs/2026-07-29-visual-system-reconciled.md` | §4 offset value; §4 state-mapping row for `stale` |
| `DEVIATIONS.md` | one row per judgement call, in the existing table format: `date, doc§, question, decision, rationale, files` |
| `reports/frontend_probe_rev2.md` | new — your report |

**The report must contain:** a before/after screenshot pair at 1440px; the offset value you chose and why; your own answer to the calm-vs-quiet question now that the shell is present; and anything you think the spec still gets wrong.

---

## 6. Verification before you report done

1. Render at exactly 1440px wide and screenshot full-page. Chrome DevTools MCP or Playwright, whichever is available.
2. Put the rev-2 screenshot beside `frontend/design/probes/plate-and-proof-still-1440.png` and beside a fresh screenshot of the running app's landing page (`cd frontend && npm run dev`, then `/` at 1440px).
3. Answer these explicitly in the report — do not skip one because it is uncomfortable:
   - Does the offset plate read as a second printing plate, or still as a shadow?
   - Do the five states read as five distinct states? Specifically, can you tell `stale` from `estimated` at a glance?
   - Does the document language sit inside the shell, or fight it?
   - Is anything unreadable? (Re-check the stamp.)
4. `node frontend/check-contrast.mjs` if it applies to any pairing you changed.
5. `cd frontend && npx tsc --noEmit` — must still exit 0.
6. `git status` — confirm nothing under `frontend/src/`, `backend/`, or `docs/specs/` is modified.

---

## 7. Skills to invoke

- `superpowers:using-superpowers` — first, before anything else.
- `frontend-design` — **before writing any CSS.** This is aesthetic work; the failure mode of rev 1 was treating it as mechanical.
- `superpowers:verification-before-completion` — before reporting done.
- `claude-in-chrome` **or** the `chrome-devtools` MCP — for the 1440px screenshots.

Do **not** invoke `superpowers:brainstorming` or `superpowers:writing-plans`. The direction is decided in the spec; this is execution against a known set of defects.

---

## 8. The one thing to get right

Rev 1 satisfied the spec's letter — it is a genuine +6/+6 no-blur celadon offset — and still failed, because 6px of the palette's lightest colour cannot carry an idea. Do not optimise for matching the spec text. Optimise for whether a person looking at the render believes these are issued documents sitting in a calm room. If the honest answer after your revision is still no, say so plainly in the report. That is a useful result and the spec changes, not the probe.
