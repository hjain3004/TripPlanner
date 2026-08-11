# Frontend design contract — Japan philatelic reconciliation

This is the editable frontend design contract for the current TripPlanner visual system. It points to, and must stay consistent with:

- `docs/superpowers/specs/2026-08-09-japan-frontend-foundation-design.md`
- `docs/superpowers/specs/2026-08-11-japan-philatelic-figma-reconciliation-design.md`

The raw Figma Make export is reference-only. Do not import it wholesale, copy its runtime structure, or let it override typed data, provenance, accessibility, or the deterministic frontend contract.

## Typography

| Role | Family | Allowed contexts |
|---|---|---|
| Display | Poiret One, 400 only, stroked by theme tokens | Page hero/H1 and approved large marks only |
| UI | Schibsted Grotesk | H2–H6, card titles, navigation, body, buttons, form controls, all money, points, dates, and dense functional text |
| Metadata | Roboto Mono | Provenance, trace IDs, airport codes, timestamps, technical labels, and small metadata only |

Poiret One is never faux-bold. Use `display-hero` for page-level display and `display-mark` for approved marks; do not combine display classes with `font-bold`, `font-semibold`, or numeric containers.

## Theme scope

Japan Quiet Blossom is the golden destination pack. Natural is the fallback. Runtime theme resolution is deterministic and allowlisted:

- explicit `JP` → `theme-japan`;
- null, unknown, unsupported, lowercase after normalization, or free-form city strings that are not explicit country codes → natural unless the normalized code is `JP`;
- no browser locale, geolocation, LLM, city-name guessing, or network lookup.

Singapore-specific visual instructions are obsolete for this reconciliation and must not be reintroduced.

## Color and tone

The interface is light-only and uses semantic theme tokens. It forbids:

- black, `#000`, `bg-black`, `text-black`, `border-black`, or equivalent raw black utilities;
- neon/synthwave/glow treatment;
- blurred/glowing shadows;
- raw color literals in product/app source except documented technical escapes already covered by lint suppression.

Japan Quiet Blossom should feel like warm paper, soft blossom, olive, brass, and ink. The natural pack is a calm fallback, not a second destination skin.

## Shape, depth, and surface rules

Principal product surfaces are square editorial panels:

- `rounded-none` or token-driven zero-radius containers for main surfaces;
- 2px destination-ink rules for principal panels;
- zero-blur hard offsets (`shadow-1`, `shadow-2`, `shadow-3`) rather than soft card shadows;
- rounded geometry remains only for semantically round controls, chips, nodes, and the eventual stamp artifact.

Hover states may shift color, border, or small press feedback. Do not use generic hover lift on non-interactive cards.

## Motion

Motion is restrained and purposeful:

- no `transition-all`;
- no `initial={{ scale: 0 }}` or blank scale-zero entrances;
- reduced-motion users must land on the final visible state immediately;
- route/graph line drawing may remain when it conveys structure;
- confetti and generic celebration effects are out of scope.

Use explicit transitions such as color, border, shadow, opacity, or transform only where the interaction requires them.

## Philatelic placement contract

Philately is Japan-only and presentation-only. A stamp is a fictional Atlas artifact, not legal postage, proof of verification, a booking, a transfer, an airline/hotel endorsement, or a government-approved document.

Stamp placement is limited to approved editorial destination surfaces. Do not place a stamp on:

- money, points, transfers, savings, fees, or offer calculations;
- provenance, trust badges, warnings, errors, or verification state;
- account, wallet, passport, or credential surfaces.

The stamp must enter through an explicit typed prop from an approved asset allowlist. No component may infer Japan from free-form city text, fetch an asset, call a generator, or mutate trust state.

## Data and provenance

Frontend components render typed report fields. They do not compute travel finance outcomes, savings, transfer paths, provider trust, or availability. Every displayed financial number must be present in a fixture/report artifact and remain covered by no-orphan-number tests.

Sample visual evidence must be visibly labelled as sample data and must not claim live provider access, account synchronization, seat availability, active bonuses, passport storage, or verified booking inventory unless those exact typed facts exist.
