# ANTI_GENERIC.md — Why each product wrapper exists

## RouteSpine / RouteNode

A route is not a step list. `RouteSpine` + `RouteNode` encode the four-state model (done/current/pending/warning) that maps to travel itinerary progression states — not to generic wizard steps. The SVG-alternative approach (CSS pseudo-elements for the connecting line, border-2 dots) keeps it accessible and avoids SVG-in-JSX complexity for a linear list. If we ever need branching itineraries, the state model extends with `dot-dot-dot` dashed lines.

## DecisionLedger / LedgerRow

Financial comparisons need ruled tables with dominant rows, not generic data tables. `DecisionLedger` is a pricing comparison table that inherits the accent-2 highlight for the chosen/dominant row. `LedgerRow` uses `tabular-nums` by default and supports a `notch` prop that breaks the left margin with an accent-4 rule — a product-specific pattern that no generic table component would provide.

## MoneyText

Spec 02 §3.1 is clear: money arithmetic is integer minor units with currency. `MoneyText` enforces `minor / 100` conversion at render time so no frontend code path ever computes money math. Every currency display in the app goes through this component, ensuring consistent `en-IN` formatting and tabular-nums. This is a safety gate, not a convenience.

## ProvenanceBand

Every non-trivial fact needs a source, verification date, verifier, and confidence score — not just a footnote. This component renders the full provenance record on every displayed fact. It's deliberately verbose and cannot be "styled away" to a single icon, because spec 03 §6 requires trust badges propagate to the UI.

## TrustChip

Three-state (verified / warning / needs-verification) visual badge for provenance confidence. Maps directly to the `needs_verification` and `confidence` columns in the backend data model. `needs-verification` maps to the accent-2 "informational" state rather than a false-positive "negative" state, because unverified data is not necessarily bad data.

## WhyThis

An inline, expandable rationale that keeps the primary UI clean while satisfying the spec 04 §3 requirement that every recommendation carries reasoning. Uses `AnimatePresence` for height animation. Content is always in the DOM (hidden via `AnimatePresence` exit) to avoid layout shift when expanded. This is not an Accordion — it's a single-disclosure pattern tied to a specific recommendation, not a multi-panel widget.

## NotchLabel

A ruled-surface-interrupting label that calls out a key insight or recommendation. Uses accent-4 (lacquer) as a left-border accent, capped at <2% of any screen's surface. This is a deliberate hyper-specific component: it only exists because spec 10 §2 requires accent-4 usage to be constrained and intentional.
