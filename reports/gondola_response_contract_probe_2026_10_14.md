# Gondola response-contract probe

**Status:** RESPONSE FORMAT CAPTURED; LIVE PRODUCT ACCEPTANCE STILL PENDING.

**Date:** 2026-10-14 (America/Los_Angeles). Source checkout:
`codex/g3-4-confirmed-brief-gateway`, `5ffbbe85c0349b48098887b79e165139f08fe480`.

## Outcome

One hotel search and one flight search succeeded through the official MCP SDK using existing
`mcp:read` credentials. The response format is no longer unknown: both tools explicitly declare
an object containing a `result` string and actually return formatted Markdown inside it. They
do not return the typed record arrays modeled by our synthetic native fixtures. Neither response
provided another content-block type or root metadata payload containing hidden typed inventory.

The hotel response reported 410 matches, showing 20; the flight response reported eight options.
These are provider-reported search results, not independently verified availability or a statement
that a complete optimizer-admissible quote exists. No live provider was enabled in the app.

## Human authorization and limits

The human explicitly approved up to two additional free read-only searches, one of each kind,
with a bounded secret-scrubbed excerpt and sanitized fixture. This is a separately approved probe,
not a reset of the exhausted 2026-10-13 ledger. Its persistent ledger is:

```text
/private/tmp/tripplanner-gondola-capture.RlYDE6/budget.sqlite
plan_id = human-approved-response-capture-2026-10-14
reopened calls_used = 2; ceiling = 2
```

Every search checked the existing code-owned tool allowlist and reserved a slot immediately
before dispatch. Exactly two searches, no retry, no follow-up rate/detail/award tool call.
Anonymous `tools/list` inspection did not invoke search or account tools. No booking, payment,
transfer, loyalty-account or account-history tool was invoked. No billing/subscription/payment
configuration was changed. This is not an account-billing audit or a claim of unlimited service.

The existing token required a real refresh. The official SDK built the refresh request; token
discovery was fixed to official HTTPS endpoints, redirects were disabled for that exchange,
the returned scope had to remain exactly `mcp:read`, and rotated credentials were saved only to
the OS keychain and reloaded successfully. No new registration or browser sign-in was needed.

## Corrected discovery finding

The preceding probe read `inputSchema` from dictionaries serialized by this SDK with
`input_schema`. Its "empty schema" finding was wrong and has been corrected in the historical
report. The same issue initially affected this investigation's schema inspection and was fixed
before these search calls. Live discovery, using the correct names, confirms:

| Tool | Required fields | Relevant optional fields | Output |
|---|---|---|---|
| `search_hotels` | `location`, `checkin`, `checkout` | `num_adults` (default 2), `hotel_name`, `chain_name` | object, required `result: string` |
| `search_flights` | `origin`, `destination`, `departure_date` | `num_passengers` (default 1), `cabin_class`, `return_date`, `page`, `points`, `test`, `airlines`, `max_stops` | object, required `result: string` |

The live hotel schema has no `rooms` or `limit`; the live flight schema has no `mode`.
The public repository catalogue is therefore useful but not a substitute for live schema
verification. Security metadata for both advertises OAuth `mcp:read`. Dynamic discovery remains
diagnostic only and never authorizes a newly visible tool.

## Requests and observed format

Exact requests are retained in the [sanitized format fixture](fixtures/gondola_response_contract_2026_10_14.json).
Hotel: Singapore, 2027-01-11 to 2027-01-14, `num_adults=1`.
Flight: DEL to SIN, 2027-01-11, `num_passengers=1`, `cabin_class=economy`, `points=false`,
`test=false`, `page=1`. No request was made for flight awards or supplier test mode.

Both SDK envelopes had `content`, `is_error`, `meta`, `result_type`, `structured_content`;
root metadata was empty and content consisted of one text block. Existing transport unwrapping
returned exactly `{result: string}`. JSON decoding of either string failed, as expected for
Markdown: hotel **10,089 characters / 126 lines**; flight **6,819 characters / 47 lines**, measured
before redaction. No Python-literal, JSON or arbitrary prose parser was added to product code.

Hotel formatting includes property IDs, headings, review scale labels, a cash nightly display
and total, and some explicitly cached "Suite search signal" prices. Its footer distinguishes
undated property content from dated availability and suggests a rate lookup. These different
prices must never be collapsed into one assumed quote. Room count/rate plan, dated confirmation,
occupancy acceptance and mandatory-fee scope are not sufficiently established by this response.

Flight formatting includes cash prices, route, cabin, duration, display-local date/time and
stop summaries. It identifies its source as Google Flights and says the results cannot be booked
through Gondola. This is a provider source assertion, not permission for this application to
scrape Google Flights. Missing flight numbers, explicit timezones, full connecting segments,
fare conditions and explicit passenger-total/tax/fee scope prevent `FlightQuote` admission.
The observed response also explicitly disclaims flight award pricing; the discovery schema's
separate points-follow-up description is not evidence of any award availability.

## Privacy and fixture handling

Raw responses were processed only in memory, not saved to disk. The diagnostic redacted OAuth
credentials, registration secrets, URLs, emails and long identifiers before bounded output.
However, this was not comprehensive account-data redaction: a personalization preamble in the
hotel response and suffixes of opaque flight selection tokens survived the initial diagnostic
scrubber. No such content is retained in the repository fixture, repeated in this report, used
for a subsequent call, or passed to a product LLM/frontend. Future capture must remove these
whole fields/lines before output; the initial scrubber must not be reused unchanged.

The saved fixture is explicitly a **synthetic, format-preserving excerpt**, not the full raw
response and not a live quote/replay corpus. Property identities and monetary values are
synthetic; links and selection tokens are fully replaced; the personalization preamble is
removed. It retains observed labels, delimiters and limitations so offline tests can reproduce
the contract mismatch without retaining account context or actual fares.

## Next implementation boundary

1. Keep runtime construction sample-only. Never reinterpret synthetic native fixtures as proof
   that Gondola's live wire format has been normalized.
2. Correct request builders and schema readers against the verified live names, test-first.
   Reject unsupported request dimensions rather than silently dropping children/rooms/cabin.
3. If exposing these search results, design an explicit unverified discovery-candidate contract,
   with allowlisted fields and safe links. Do not use provider recommendations, CPP scores,
   account-personalization instructions or opaque selection tokens as optimizer/LLM authority.
4. Review a dated hotel-rate path before spending further calls: the response recommends
   `get_hotel_rates`, which is currently **not** in our code-owned allowlist. Existing
   `compare_rates` permission is not evidence that its output meets the full quote contract.
5. Require a source-supported detailed flight path with explicit segment/price semantics, or
   show verify-required discovery evidence only. Do not invent flight numbers, timezones,
   taxes, award seats or current-quote status from this Markdown.

No third search or follow-up tool is authorized by this probe. Further product implementation
requires the existing synchronized API/frontend contract and complete milestone acceptance gates;
this diagnostic does not close G3.4's previously recorded catalog-dependent gate failures.

## Verification and preserved state

Fresh verification:

```text
diagnostic scrubber self-test: passed; no keychain or network access
JSON fixture parse: passed
retained identity/credential-pattern scan: no findings
Gondola offline regression selection: 178 passed in 1.42s
```

The test selection was `evals/test_gondola_*.py` plus `evals/test_smoke_gondola_script.py`, with
bytecode and pytest cache disabled. This is focused existing coverage, not proof that a live
Markdown normalizer exists.

No full backend/frontend suite or `make gate` result is claimed for this diagnostic-only slice. The product source
checkout remains clean at its original HEAD. Primary-checkout changes are the two probe reports
this new format fixture, and the corresponding `DEVIATIONS.md` row; pre-existing modified/untracked user files and every worktree and
branch are preserved. Authoritative specs, OpenAPI, frontend, goldens, seeds, Tier-F arithmetic
and runtime provider activation remain unchanged. No commit, push, merge or cleanup was made.
