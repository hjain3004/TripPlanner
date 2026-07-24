# 15 — Wit & Quip Content Pack

Personality layer for waits and micro-moments. MVP = static curated packs; the interface is designed so a future LLM generator slots in without touching consumers.

## 1. Rules of the voice (Tier F)

1. **Original lines only.** No verbatim movie/anime/song quotes, no trademarked catchphrases, no character names, no brand names (airlines/banks included). "In-the-style-of" is the technique: evoke the vibe of a genre without quoting or naming it. (Basis: short-phrase trademark risk + India's closed fair-dealing list — see frontend research report. Attribution does not cure this; don't attribute, don't quote.)
2. Never joke about: money lost, card debt, visa/immigration, safety, religion, politics, or the user's choices. The wait for a financial recommendation is a trust moment — wit warms it, never undermines it.
3. Destination humor punches at the *traveler experience*, never at the place or its people. Singapore examples of the register: hawker-queue devotion, MRT punctuality awe, air-con dependence, kaya-toast breakfast seriousness, the chili-vs-black-pepper crab debate.
4. English MVP; structure is i18n-ready (keys, not concatenation).
5. Length ≤ 90 chars; readable in one glance; no emoji in MVP (theme decides later).

## 2. Pack format `content/quips/<destination>.json`

```json
{
  "destination": "singapore",
  "version": 1,
  "quips": [
    { "id": "sg-001", "text": "Calculating whether the hawker uncle would approve of this budget.",
      "categories": ["costing"], "tone": "playful", "approved": true },
    { "id": "sg-014", "text": "Optimizing your cards harder than aunties optimize buffet lines.",
      "categories": ["optimizing"], "tone": "playful", "approved": true },
    { "id": "sg-021", "text": "Your itinerary is being timed to MRT precision.",
      "categories": ["itinerary", "generic"], "tone": "warm", "approved": true }
  ]
}
```

`categories` ⊆ pipeline stages (`intake, itinerary, costing, optimizing, transfer, critic, explaining`) + `generic` + `results_celebration`. `approved` is a human sign-off bit — unapproved lines never render (the loader filters; a test asserts the filter).

## 3. Runtime behavior

`useQuips(destination, stage)`: prefer current-stage quips, fall back to `generic`; shuffle **seeded by job_id** (deterministic per run — reproducible demos, no repeat-flicker on re-render); never repeat within a session until the pool is exhausted; rotate 6s crossfade (13 §3); decorative (`aria-live=off`). Missing pack for a destination → generic pack (`_generic.json`, destination-neutral travel lines) — a new destination without quips degrades gracefully, never crashes (asserted in the theme-pack DoD, 11 §5).

MVP inventory: Singapore ≥ 40 approved lines covering every stage (≥ 4 each) + ≥ 10 generic + 3 `results_celebration` (used once under the verdict header, small caption). Author in bulk, curate hard: write 3×, keep the best third.

## 4. Future LLM mode (design now, build later)

`QuipSource` interface: `getQuips(destination, stage, tripContext) → Quip[]`. Static packs implement it today. The future LLM implementation: generated **offline in batches** into the same JSON format + human `approved` pass — *not* live per-request generation. Rationale: live generation adds latency and an unreviewable brand-voice risk to every load for near-zero freshness benefit; batch+approve keeps the human sign-off bit meaningful and costs pennies. Trip-aware personalization (e.g. interest-aware quips) is expressible later via `categories` expansion without consumer changes. This decision is Tier C — revisit only with a DEVIATIONS entry arguing why live generation earns its risk.
