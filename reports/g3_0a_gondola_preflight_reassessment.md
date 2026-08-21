# G3.0a — Gondola Preflight Reassessment (supersedes G3.0's live-activation hold)

**Milestone type:** Research and decision-record only. No adapter code, MCP client, OAuth flow, or
live call was written or executed in this report. `reports/g3_0_gondola_preflight.md` is preserved
unmodified below this report — it is the historical record of the decision made from the evidence
available on 2026-08-20, and remains correct as a description of *that* evidence and *that*
decision. This report does not rewrite it; it records why the decision changes given newer,
clearer official evidence gathered in this session (2026-08-21).

**Branch:** `feat/g3-gondola-readonly-mcp` (worktree at `.worktrees/feat-g3-gondola-readonly-mcp`),
branched from `main` @ `43c4191` (G1+G2 merged, unchanged from G3.0's base).

---

## 1. What changed and what didn't

G3.0 reached **decision B** (offline-fixture-only, live activation withheld) on the strength of
four findings, evidenced against Gondola's own public pages as they stood on 2026-08-20. This
session re-fetched three of Gondola's own pages directly (`gondola.ai/mcp`,
`gondola.ai/help/mcp-oauth-integration`, `gondola.ai/terms-of-service`) plus the official MCP
Python SDK's GitHub page, on 2026-08-21. Re-verifying rather than assuming was the point: two of
G3.0's four blocking findings are resolved by clearer official evidence than G3.0 had; two are
**not** resolved and are carried forward unchanged, now as accepted, mitigated residual risk under
an explicit human decision rather than as blockers.

| # | G3.0 finding | Status after re-verification | Basis |
|---|---|---|---|
| 1 | ToS anti-automation clause contradicts the MCP product; no carve-out found | **Unresolved, confirmed unchanged** — see §2 | Direct re-fetch of `gondola.ai/terms-of-service`, 2026-08-21 |
| 2 | `search_flights` requires sign-in this project had no plan to obtain; flight coverage possibly US-centric | **Superseded by a human architecture decision**, not by new technical evidence — see §3 | Direct re-fetch of `gondola.ai/mcp` and the OAuth guide, 2026-08-21; the decision to build a one-time developer-owner OAuth bootstrap is this milestone's own authorization, not a Gondola-side change |
| 3 | Geographic coverage for India/UAE/Singapore/Europe/UK is undocumented; one independent report showed a relevance bug | **Still unresolved — carried forward as an open, empirically-testable question**, not a blocker | No new coverage evidence was found this session; §6 below records this as a bounded live-acceptance question, not a pre-condition |
| 4 | No documented rate limit / zero-spend ceiling for the MCP specifically | **Still undocumented by Gondola — carried forward**, now mitigated by this project's own ledger/circuit-breaker/kill-switch rather than by a Gondola-published guarantee | `gondola.ai/mcp`'s "Completely free. No account, no API key, no credit card" language is explicit for the anonymous tools (confirmed again, 2026-08-21) but is not a rate-limit or fair-use policy |

The net effect: **two of four original blockers are unchanged facts**, but the human authoring this
milestone has made an explicit, informed decision to proceed under those two accepted risks for a
personal, non-commercial, bounded, fail-soft integration — which is a legitimate Tier-appropriate
call (CLAUDE.md reserves "legal/compliance wording" for human judgment, not code) — not a claim
that G3.0's evidence was wrong.

---

## 2. Terms of Service — re-verified, contradiction confirmed unchanged

Direct fetch of `https://www.gondola.ai/terms-of-service`, 2026-08-21:

- **Date of Last Revision: January 30, 2024** — identical to G3.0's citation. The ToS has not been
  updated since the MCP product (last updated June 20, 2026 per the OAuth guide) was published.
- **Anti-automation clause, exact text, unchanged:** *"you will not access, monitor or copy any
  content on our Service using any robot, spider, scraper or other automated means or any manual
  process."*
- **Personal/non-commercial clause, exact text, unchanged:** *"you will only use the Service for
  personal and non-commercial purposes."*
- **No MCP/API/developer carve-out exists anywhere in this document**, confirmed again by direct
  re-fetch, not assumed from G3.0's prior finding.

**Recorded factually, per this milestone's explicit instruction, without resolving it as a legal
question:** Gondola's general Terms of Service and its own officially-published, actively-marketed
MCP product are in unaddressed tension. This report does not conclude MCP use violates the ToS —
that remains outside any code milestone's authority — and does not claim Gondola has resolved the
contradiction. What has changed is the human decision on *how this project treats that residual
risk*: proceed for a personal, non-commercial, deliberately bounded, fail-soft integration using
only the officially-published, intentionally-exposed MCP interface (never scraping the general
website, never exceeding what Gondola itself documents as the MCP's own surface), rather than
withholding all live activation pending written clarification. This is the human's call to make,
consistent with CLAUDE.md's own list of what requires human sign-off ("legal/compliance wording
changes"), and it is being made explicitly and recorded here, not silently assumed by an agent.

---

## 3. Authentication and `search_flights` — re-verified, framing corrected

Direct fetch of `https://www.gondola.ai/mcp`, 2026-08-21, confirms the same tool-tier split G3.0
already found (19 anonymous tools; a sign-in tier including `search_flights`; a partner-only
`mcp:book` tier), with one detail G3.0's own table already had right but that matters more now:
`search_flights` requires only the **`mcp:read`** scope — not `mcp:book`, not a special
partnership. Direct fetch of `https://www.gondola.ai/help/mcp-oauth-integration`, 2026-08-21,
states the scope's definition explicitly: *"mcp:read: Search, plus reading the member's own trips,
loyalty accounts, and saved searches. Granted by default when `scope` is omitted."*

**What actually changed is not this technical fact — G3.0 already reported the correct tier — but
the architectural decision built on it.** G3.0 declined to pursue `search_flights` because *"this
project's architecture (a stateless, non-account-bound deterministic kernel demo) is not designed
to obtain or manage [a per-user OAuth login] for a backend service call."* That framing implicitly
assumed the only two options were "no OAuth" or "an arbitrary end-user's OAuth token flowing
through a stateless backend" — and correctly ruled the second one out. It did not consider a third
option, which this milestone now adopts: **a one-time, explicitly-labeled, developer-owned OAuth
connection**, bootstrapped locally by the human running this project, with tokens held in an
OS-backed secure store (never in the repo, never in a request from an anonymous end user). The
OAuth guide itself frames the whole document around exactly this shape of integration: *"This guide
is for developers building their own MCP client or integration on top of the Gondola MCP server,"*
and the `/mcp` page's own audience framing — *"Whether you're building an AI travel app, searching
trips from Claude, or advising clients, Gondola gives your AI the best travel data available"* —
is first-party confirmation that a developer building an AI travel app (this project, exactly) is
the intended user of this exact flow, not an edge case of it.

This is a **single-owner, local/student-demo connection**, not a general multi-tenant "the
developer's account silently serves the public" pattern — see §9 for the explicit non-goal this
draws.

**Flight coverage (US-centricity concern):** G3.0's independent-evidence concern about US-centric
flight coverage is not addressed by anything fetched this session — no new coverage evidence
exists. It remains an open, empirical question, deliberately deferred to the bounded live-acceptance
step (§6) rather than pre-answered here.

---

## 4. OAuth mechanics — re-verified in full for implementation planning

Direct fetch of `https://www.gondola.ai/help/mcp-oauth-integration`, 2026-08-21, confirms the exact
flow the revised implementation plan (§8 below) must build against:

1. An unauthenticated tool call returns `401` with a `WWW-Authenticate` header.
2. The client fetches OAuth **protected-resource metadata** to locate the authorization server.
3. The client fetches **authorization-server metadata** for the token/authorization endpoints.
4. The client registers itself via **Dynamic Client Registration** (RFC 7591) — no manual app
   registration in a developer console is required or offered.
5. The client runs the **authorization-code flow with PKCE, `S256` required** (not optional, not
   `plain`).
6. The client exchanges the authorization code for **access and refresh tokens**.
7. The access token is sent as a **bearer token** on subsequent MCP requests.

Three scopes exist, confirmed verbatim: `mcp:read` (search plus reading the member's own trips,
loyalty accounts, and saved searches — **default when `scope` is omitted**), `mcp:write` (create/
delete price alerts — must be explicitly requested and approved), and `mcp:book` (booking-partner
only). **This milestone requests `mcp:read` only, explicitly, never omitting `scope` and relying on
a default that could silently change, and never requests `mcp:write` or `mcp:book`.**

---

## 5. Official MCP Python SDK — verified suitable, supersedes the old plan's `urllib` assumption

Direct fetch of `https://github.com/modelcontextprotocol/python-sdk`, 2026-08-21:

- Published as the `mcp` package (with an optional `[cli]` extra) — official, maintained under the
  `modelcontextprotocol` GitHub organization, explicitly labeled *"The official Python SDK for
  Model Context Protocol servers and clients."*
- Supports **Streamable HTTP** transport, matching Gondola's documented endpoint shape
  (`https://mcp.gondola.ai/mcp`).
- Requires **Python 3.10+**, which covers this project's pinned Python 3.11.
- OAuth client support (authorization-code + PKCE, dynamic client registration, protected-resource
  discovery) is a documented capability of the `mcp` package's `mcp.client.auth` module; the
  GitHub landing page excerpt fetched this session did not itself enumerate every auth helper in
  prose, so **Phase 2 implementation must confirm the exact installed-version API surface
  (`mcp.client.auth.OAuthClientProvider` or equivalent) against the installed package's own
  documentation before writing code against it**, rather than assuming this report's fetch was
  exhaustive. This is recorded here as an implementation-time verification step, not left implicit.

This directly supersedes `docs/superpowers/plans/2026-08-20-g3-gondola-live-adapter.md`'s Tech
Stack line (*"No new third-party dependency. Uses stdlib `urllib`/`json` for the live transport"*).
A hand-rolled `urllib` client cannot perform MCP session initialization, `tools/list`/`tools/call`
framing, or the OAuth discovery/DCR/PKCE/refresh flow correctly without reimplementing large parts
of the MCP and OAuth 2.1 specs — exactly the risk the parent task's instructions flagged. `mcp` is
added as a new, pinned backend dependency (see §8, Phase 2).

---

## 6. Geographic coverage and rate limits — still open, now explicitly bounded rather than blocking

Neither of G3.0's remaining two open findings (§8 and §9 unknowns in the original report:
India/Singapore/UAE/Europe/UK coverage; MCP-specific rate limits) is resolved by any evidence
gathered this session. Per the parent task's explicit instruction, these are **not** re-litigated
as blockers. They are instead the two things the bounded, one-time live-acceptance step (spec'd in
§6 of the revised plan, and the parent task's "Bounded live acceptance" section) exists to observe
empirically, safely, and cheaply:

- One anonymous hotel search for a supported project destination answers the coverage question
  directly, for that one destination, with real data instead of marketing copy or a single
  third-party anecdote.
- One authenticated `search_flights` call for DEL→SIN answers the flight-coverage question the
  same way.
- Both calls are metered through this project's own ledger (`max_cost_minor=0`, hard call
  ceiling), so an undocumented Gondola-side rate limit is a reliability concern this project
  defends against with its own circuit breaker — never permission to make unlimited calls, exactly
  as the parent task states.

If either bounded call shows the corridor is not meaningfully covered, that is a **result** to
record honestly (per the parent task: *"If OAuth or live search cannot be completed, do not
pretend G3 live activation passed"*), not a reason this preflight reassessment was wrong to
proceed to fixture-first development now.

---

## 7. Revised decision

**Eligible for fixture-first development and bounded, read-only live activation**, using anonymous
Gondola hotel search and authenticated (`mcp:read`) `search_flights`, under the
`student_noncommercial` profile. Booking, payments, mutations, and commercial use remain
prohibited absolutely — nothing above changes that. Evidence from Gondola remains **experimental**
and every code path that touches it must be **fail-soft to `SampleAdapter`**. This decision
supersedes G3.0's decision B *for the purpose of proceeding past offline-only work*; it does not
retroactively call G3.0 incorrect — G3.0 correctly declined to proceed without either (a) newer
evidence resolving its blockers or (b) an explicit human risk-acceptance decision for the ones that
don't resolve. Both now exist, are recorded above, and are attributed correctly: (a) for the
`search_flights`-scope and SDK findings, (b) for the ToS-tension and rate-limit/coverage
findings.

---

## 8. Plan correction summary

`docs/superpowers/plans/2026-08-20-g3-gondola-live-adapter.md` is superseded by a new plan,
`docs/superpowers/plans/2026-08-21-g3-gondola-readonly-mcp.md`, written in this same commit
sequence. The two load-bearing corrections it makes relative to the old plan:

1. **Transport:** the official `mcp` Python SDK (Streamable HTTP + OAuth client), not hand-rolled
   `urllib` (§5 above).
2. **Scope:** `search_flights` is implemented (authenticated, `mcp:read`), not declared
   `unsupported_domain` (§3 above).

Every other G3.0/old-plan safety property is preserved unmodified in the new plan: static tool
allowlist as a hardcoded, non-LLM-selected constant; disabled-by-default live transport gated by an
explicit environment flag checked at registry-construction time; `SampleAdapter` fallback always
available; persistent call ledger; circuit breaker; zero-network normal test suite;
`backend/core/` never imports `gateway/`; no golden-value or contract change implied by this
milestone alone.

---

## 9. Explicit non-goals restated (unchanged from the parent task's instructions)

- This is a **single, explicitly-labeled local/student-demo owner connection** — the developer's
  own Gondola account, authorized once via browser, tokens held in the OS keychain. It is **not**
  a hidden production credential silently serving arbitrary public users of a deployed instance. A
  future multi-user product would require per-user account linking and encrypted server-side token
  storage — out of scope here and not implied by this milestone.
- `mcp:book` is never requested. Booking, payment, cancellation, and mutation tools are never
  called, regardless of what `tools/list` returns at runtime — tool availability from the server is
  not authorization (parent task, "Tool policy").
- Gondola's own provider-computed points/rewards guidance (`predict_price`,
  `optimize_loyalty_portfolio`, `credit_card_coverage`, and the points-rate fields embedded in
  `search_hotels` responses) is never trusted as kernel arithmetic. This project's deterministic
  kernel recomputes every financial comparison independently, exactly as it already does for every
  other provider (CLAUDE.md non-negotiable #1).

---

## 10. Explicit confirmation

Three of Gondola's own pages and the official MCP Python SDK's GitHub page were fetched directly in
this session (2026-08-21) for verification. No MCP client was installed, connected, or configured.
No credential, account, API key, or OAuth token was created or used. No provider quota was
consumed. No paid service was enabled. No runtime code, configuration, or environment flag was
modified or activated by this report. No booking, hold, payment, or transfer tool was invoked or
tested. `reports/g3_0_gondola_preflight.md` is unmodified and remains the historical record of the
2026-08-20 decision.
