# Reconciled Visual System — calm shell, issued documents

**Date:** 2026-07-29
**Status:** DESIGN — authoritative visual spec resolving conflicts between Figma, Plate & Proof, and F1 contracts.

---

## 1. Context and The Organising Idea

The frontend previously had three competing visual sources of truth (Figma's calm editorial layout with sharp edges, Plate & Proof's printing metaphor, and F1's soft layered shadows).

This document reconciles them into **calm neobrutalism**: a soothing shell where computed artifacts read as issued travel documents.

**The Organising Idea:** The document treatment is not a borrowed aesthetic shadow. It is the existing **plate and proof printing metaphor** taken literally. A second plate slightly **out of register** produces the offset colour block. This gives a principled rule for when the offset appears, and makes contradictions render as literal misregistration.

---

## 2. Conflict Resolutions

| Conflict | Resolution |
|---|---|
| Figma bundle vs Plate & Proof | **Figma wins composition, layout, page structure.** Plate & Proof wins palette, the register system, and the posterized illustration technique. |
| Soft shadow (Tier-F depth rule) vs offset plate | **Scope the rule.** Shell surfaces keep surface-tint + layered shadow + hairline. The `issue` register uses an offset plate, no blur. (Logged in DEVIATIONS.md). |
| 1px hairline vs 2px ticket rule | **No amendment needed.** `CONTRACT.md:132` already permits a heavier rule where "a component contract explicitly calls for" one. The `issue` register is such a contract. |
| `--radius-m: 12px` vs `rounded-none` | Shell keeps its radii. `issue` register is `0`. Both correct in their own scope. |
| accent-4 <2% budget vs stamps | Budget holds. Lacquer becomes **mandatory on exactly one thing** — `verify_required` — and optional nowhere. |

---

## 3. The Register System

The palette relies on a system of four registers, establishing strict meaning for colours:
1. `structure` (mangrove lines): rules, nodes, drawn lines.
2. `signal` (lacquer): the one thing currently being explained. Nothing is signal at rest.
3. `value` (brass): money saved, only.
4. `issue` (celadon block): an earned document treatment.

---

## 4. The `issue` Contract

> **The document treatment is earned, not decorative.** An element renders as an issued document if and only if it represents a computed artifact the kernel produced and a validator checked. Nothing decorative is ever a ticket.

**Form:**
- Sharp corners (radius `0`).
- A solid `celadon-1` block offset `+6px/+6px` with **no blur**.
- A 2px mangrove rule (`structure`).
- Mono field labels uppercase at ~10–11px with `0.16em` tracking.
- Schibsted Grotesk heavy for data fields and airport codes.
- Bodoni Moda on the calm shell **only**, never inside a document.

**State Mapping (FreshnessState):**

| Status | Treatment |
|---|---|
| `live` | full offset plate, crisp registration (`celadon-1`) |
| `cached` | offset plate in `celadon-2` (lighter) |
| `estimated` | dashed 2px rule, **no** offset plate — nothing was issued |
| `stale` | plate greyed, diagonal `STALE` overprint |
| `verify_required` | lacquer stamp — the one place lacquer is mandatory |

**Lifecycle Mapping (LifecycleState):**

| Status | Treatment |
|---|---|
| `active` | default plate |
| `superseded` | graph-lifecycle treatment with diagonal `SUPERSEDED` overprint |

**Graph Concepts in UI:**

| Graph concept | Treatment |
|---|---|
| `CONTRADICTS` edge | two plates visibly out of register — double-vision offset |
| `DERIVED_FROM` lineage | printed verification strip along the bottom edge, mono |
| transfer plan | detachable stub, perforated rule (dotted `border-top`) |
| verify-before-transfer | boarding-pass checklist row, unticked box, lacquer |
