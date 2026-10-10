# Frontend design contract — Japan-first current direction

**Status:** reconciled documentation for the integrated CP2/Japan implementation; not a claim that
CP3, G3.4, or every future J-phase item is complete.

This contract points to the approved Japan foundation inputs:

- `docs/superpowers/specs/2026-08-09-japan-frontend-foundation-design.md`
- `docs/superpowers/specs/2026-08-11-japan-philatelic-figma-reconciliation-design.md`

The raw Figma/Framer material is reference-only. Runtime source, typed API data, provenance,
accessibility, and the deterministic frontend contract always win over visual experiments.

## Typography

| Role | Family | Allowed contexts |
|---|---|---|
| Display | Poiret One, 400 only, stroked by theme tokens | Page hero/H1 and approved large marks |
| UI | Schibsted Grotesk | H2–H6, card titles, navigation, body, buttons, form controls, money, points, dates, and dense functional text |
| Metadata | Roboto Mono | Provenance, trace IDs, airport codes, timestamps, technical labels, and small metadata |

Poiret One is never faux-bold and never used for money, points, or dense UI. `display-hero` and
`display-mark` are the approved display roles. Bodoni Moda is historical F1 documentation and is
not part of this current contract.

## Theme resolution

Japan Quiet Blossom is the approved golden destination pack. Natural is the safe fallback. The
implemented resolver is deterministic and allowlisted:

- explicit normalized `JP` → `theme-japan`;
- null, unknown, unsupported, lowercase after normalization, or free-form city strings → natural
  unless the normalized country code is `JP`;
- no browser locale, geolocation, LLM, city-name guessing, or network lookup.

The root layout passes `null`, so the ordinary shell uses the natural fallback. Japan is selected
explicitly by the theme-proof/kitchen-sink visual proof surfaces and by typed Japan fixtures. This is
visual fixture selection, not a claim that the live travel data is Japanese or that the planning API
queries Japan.

Singapore-specific visual instructions and the old soft-rounded default are superseded for this
Japan-first reconciliation. Singapore remains in legacy fixtures/content and in the existing
Singapore theme file for compatibility.

## Color and tone

Use semantic theme tokens only. The light-only Japan pack is warm paper, soft blossom, olive, brass,
and ink. Natural is a calm low-chroma fallback, not a competing destination identity.

Forbidden:

- pure black or `#000`, `bg-black`, `text-black`, `border-black`, or equivalent raw black utilities;
- neon, synthwave, glow, or blurred-shadow treatment;
- raw color literals in product/app source except documented technical escapes covered by lint;
- color-only status meaning.

## Shape and depth

Principal product surfaces use square editorial panels, explicit 2px destination-ink rules, and
zero-blur hard offset shadows. Rounded geometry remains for semantically round controls, chips,
nodes, and the approved stamp artifact only. Do not add generic hover lift to non-interactive cards.

## Motion

Motion is restrained and explanatory:

- no `transition-all`, scale-zero entrances, perpetual loops, or generic celebration effects;
- use explicit opacity/transform/color/border/shadow transitions only when interaction requires them;
- reduced-motion users receive the final visible state immediately;
- route/graph line drawing is allowed when it communicates travel structure.

## Philatelic placement

Philately is Japan-only and presentation-only. A stamp is a fictional Atlas artifact, not legal
postage, proof of verification, a booking, a transfer, an airline/hotel endorsement, or a
government-approved document.

Stamp placement is limited to approved editorial destination surfaces. Never place it on money,
points, transfers, savings, fees, offers, provenance, trust badges, warnings, errors, accounts,
wallets, passports, or credentials. The asset enters through an explicit typed prop and approved
allowlist; no component infers Japan from a city string or fetches/generates an asset at runtime.

## Data, money, and provenance

Components render typed report fields. They do not calculate travel finance outcomes, savings,
transfer paths, provider trust, or availability. Every displayed financial number must originate in
a fixture/report artifact and remain covered by no-orphan-number tests.

Every non-trivial fact retains its source, verification date/status, confidence, and
`needs_verification` meaning. Sample evidence is visibly labeled and must not claim live provider
access, account synchronization, seat availability, active bonuses, or verified booking inventory
unless those typed facts exist.

## Current implementation boundaries

1. CP2 conversational/profile UI is implemented, but CP3 bounded LLM interview assistance remains
   unimplemented.
2. Confirmed briefs start the existing non-live planning job exactly once; confirmation does not
   query Gondola. G3.4 remains future work.
3. Mock data remains India/Singapore-shaped (`DEL`/`SIN`, Marina Bay, INR), while typed Japan visual
   fixtures and philatelic screenshots are presentation evidence only.
4. The existing `/plan` page remains the integration point for editable itinerary behavior. Do not
   introduce an older results extraction that drops F5/F5.1 behavior.
