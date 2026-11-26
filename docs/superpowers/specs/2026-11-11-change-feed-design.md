# Change feed: contracts, persistence and nightly processing

**Status:** design ready for implementation; no runtime activation or fact approval.
**Evidence:** `origin/main` `a9efea09325a7446e9fa38c10d3d7d6bb0a1ecc0` and
`codex/firecrawl-ingestion` `b7a0057737aca9d55334bb1e24a11c41ccb5c61f`, inspected 2026-11-11.
Implements streams C/D of the November 11 work-package plan. The plans remain unpublished inputs
at this checkpoint. New model roles wait for the published owner scope decision; offline contracts
and scripted acceptance need no provider activation. Frozen arithmetic and specs remain unchanged.

## Decisions

1. **Identity and corrections.** `event_id = sha256(canonical_json(version, type, subjects,
effective_window, typed_terms))`; sort subject sets, preserve semantic list order, use strict integers
and ISO dates; identify resolved subjects by kind/KB ID, not changing display names. Exclude
observation times, quotes and snapshot hashes. Identical content is one event
with additional immutable evidence receipts. Different terms produce a different event, not an
upsert. Automatic supersession requires the same verified source occurrence (a primary promotion
URL or explicit promotion identifier); otherwise flag a possible conflict for the operator. Never
infer that two concurrent promotions replace each other from matching subjects/dates alone.

2. **Typed terms, not financial prose.** Use a discriminated union, with `extra=forbid` and bounded
text/collections. Source numbers are copied as raw strings and parsed by existing deterministic
parsers; no model conversions or inferred defaults. Missing mandatory evidence leaves a draft.

| Type | Required terms | Optional, explicitly unknown when absent |
|---|---|---|
| `transfer_bonus` | From/to programme references; `bonus_bp` in `0..100000`; quoted eligibility/effective dates | Minimum transfer points; maximum bonus points; restrictions |
| `welcome_offer` | Card reference; a tagged points bonus with programme reference OR cash bonus with ISO currency; quoted minimum spend in minor units and window length/basis | Eligibility exclusions, fee, approval/delivery time; absence blocks acquisition assessment rather than implying zero |
| `earn_rate_change` | Card/rule reference; new rate as integer points per positive minor-unit spend amount with ISO currency; quoted effective start and applicable scope | Prior rate, reward programme, cap, exclusions, end date |

Finite limits are positive integers; unknown and explicitly unlimited are separate tagged states.
Bonus/spend counts are nonnegative, earn denominators positive, and start must not exceed end.
Outliers above the bonus bound stay draft for review, never clamp. Unknown end dates remain null;
display "end date unknown" and require reconfirmation within seven days for continued publication.
These are news terms, not new kernel or `CardAcquisitionOffer` models.

3. **Subjects and trust.** `SubjectRef(kind, source_name, kb_id | None)` resolves only through exact
existing IDs or an owner-approved alias map. Unknown references stay unmapped and cannot produce
personal impacts. `lead_only` is an unverified claim; `primary_confirmed` requires a permitted primary
capture and exact evidence for every material displayed field. Neither changes the KB.
`human_approved` requires a matching owner decision plus an applied-row receipt, with field coverage;
partial review cannot upgrade the entire event. Retain source freshness and synthetic/manual/rendered
origin. Replaying a capture never refreshes its confirmation time. Public publication additionally
requires recorded owner permission to display the source summary/link; fetch permission alone is not
redistribution permission. Until then, the event remains an operator-visible draft.

4. **Two lanes and unsupported facts.** The news lane may publish a supported source change before
financial approval. The facts lane reuses FI2 validators and the existing review service only for a
complete representable row with evidence and a bound current-row hash (or validated insert).
Reuse pure validation first, then commit proposal/event/link/audit together through a connection-
accepting store helper; do not call the independently committing extractor inside that transaction.
`review_rows.SUPPORTED_TABLES` currently supports cards, reward rules, merchant offers and valuations;
it does not support transfer/programme rows or the separate welcome catalog. Validator support in
`validation.TARGET_MODELS` is not an apply path. For these gaps record
`facts_status=unsupported_target`, not a fabricated proposal or a merchant offer standing in for a
welcome bonus. Publication never invokes `decision`, `confirm-origin`, `apply` or rollback.

5. **Storage and the request boundary.** Use the existing ingestion SQLite file, so event publication,
linked proposals and audit can commit together. Firecrawl schema is v5; Flash adds v6 after that
branch lands, rechecking the actual schema first. Add immutable `feed_events` (ID/payload hash/typed
payload), `feed_evidence` receipts, CAS-versioned `feed_heads` (status/trust/first publication sequence),
append-only `feed_audit`, `feed_runs`, and `feed_steps` with unique stage fingerprints. No replace
writes; exact replay returns the prior result and conflicting ID/payload reuse is typed conflict.
Feed lifecycle/audit updates use one short `BEGIN IMMEDIATE`; no transaction spans network/model work.

Shared DTOs belong in **`backend/feed/contracts.py`**, importing no ingestion, API or accounts code.
`ingestion/events.py` re-exports those DTOs and owns offline validation; the offline writer imports
them. `feed/queries.py` opens SQLite `mode=ro`, enables `query_only`, projects public columns and
checks its supported schema without creating/migrating anything. API imports feed, never ingestion,
including transitively. Missing store returns an empty feed with `availability=not_initialized`;
incompatible schema or contention is typed 503. A single-file deployment mounts the read path
without granting the public app access to raw artifacts or curator credentials.

6. **Changed blocks and quotes.** Preserve `SnapshotDiff` and add a separate `changed_blocks` helper.
Use line offsets in the unchanged canonical snapshot strings and deterministic `SequenceMatcher`
opcodes (`autojunk=False`); include two context lines, both before/after ranges and a change kind.
Deletion-only changes remain candidates, with old evidence explicitly tied to the old snapshot;
deletion alone never proves a new rate or programme termination. Merge overlapping contexts.
Bound each version to 200,000 characters/4,000 lines, a block to 8,000 characters per side, and a
target to 32 blocks. Oversize work is `needs_review`, not silently truncated. A first capture is a
baseline, not evidence of a change unless it explicitly announces one. Default noise suppression is
off. Only owner-selected exact ignored lines/selectors may suppress blocks; never strip arbitrary
dates, percentages or digits. All evidence offsets remain absolute against original text. Verify
the artifact hash, exact slice and field meaning using existing FI2 evidence/parser checks; PDF
evidence retains the existing isolated page check. An invalid required field prevents confirmation.

7. **Triage/extraction.** Tool-less `feed_triage` receives one bounded changed block and returns
relevance plus one of the three types or `unsupported`. `feed_extract` returns typed raw terms with
field-path/quote/offset references, not a financial conclusion. One triage attempt, one extraction
attempt and at most one explicit extraction escalation; no hidden repairs. Every underlying request
uses stream A's injected budgeted `LLMClient`, including transport retries. Development uses scripted
or recorded clients, or separately authorized zero-spend access; deployed routing/model IDs come
from A, not hard-coded model names here. A real-model check on the retained Axis document is a
separate financial-extractor acceptance exercise, never a reason to re-scrape it.

8. **Resumable command.** `feed run` defaults to offline processing of retained snapshots; live
`refresh-due` requires existing explicit source/credit/activation controls. Run one operator process
at a time using a held file lock that the OS releases on death. Process in stable target/block order:
acquire/replay, diff, triage, extract, deterministic validation, publish/link, complete. Initially cap
a run at five targets and 32 blocks overall; stop at the injected model/fetch budgets, recording
remaining work. Fingerprint each step from target, before/after hashes, block range, parser/prompt/
schema/model versions and explicit extraction mode. Persist reservation/start before a model call
and validated result after it. Death between dispatch and result is `needs_reconciliation`, not an
automatic repeated call. Completed steps replay; unchanged pages call no model. Expiry/retraction
suppress current publication and invalidate dependent impacts; snapshots and audit remain intact.

9. **Public reads.** `GET /feed` and `GET /feed/{event_id}` expose published, nonretracted and
nonexpired summaries only. Use `limit=20` (maximum 50), filters for type/resolved programme and
first-seen UTC date range, and a validated keyset cursor containing last/upper publication sequence
plus filter fingerprint. New publications wait for the next first page; retractions can disappear
between pages. Unknown/unpublished detail is the same 404. Serve source links, confirmed dates and
trust labels; no raw capture, evidence quote corpus, curator token or personal impact. Escape source
text; validate links against the registered source host. Register `/feed/for-me` before the dynamic
detail route when I arrives. UI `/feed` calls the existing `/api` proxy path, avoiding route collision.

## Interfaces and ownership

These are design signatures, not permission to ship stubs. Strict DTOs include `ChangeEvent`,
`EvidenceReceipt`, `ChangedBlock`, `StepOutcome`, `PublicEvent`, `FeedPage` and future `EventImpact`
(event/user/trip/revision, result/overlay/input hashes, computed delta in minor units, basis/time).
Impact computation/storage belongs to I; C/D store no traveler data.

```python
changed_blocks(before: str | None, after: str, *, limits: BlockLimits) -> BlockOutcome
validate_event(raw: ExtractedEvent, *, evidence: EvidenceResolver,
               subjects: SubjectResolver) -> ValidatedEvent | EventRefusal
EventWriter.put_draft(event: ChangeEvent, *, client_event_id: str) -> DraftReceipt
EventWriter.publish(event: ValidatedEvent, *, evidence: tuple[EvidenceReceipt, ...],
    permission: PublicationPermission, proposals: tuple[ChangeProposal, ...],
    client_event_id: str) -> PublicationReceipt
EventWriter.retract(event_id: str, *, expected_version: int,
                    curator_id: str, reason: str, client_event_id: str) -> HeadReceipt
FeedReader.list(filters: FeedFilters, *, cursor: str | None, limit: int,
                now: datetime) -> FeedPage
FeedReader.get(event_id: str, *, now: datetime) -> PublicEvent | None
FeedRun.process(run_id: str, *, snapshots: SnapshotSource, client: LLMClient,
                limits: RunLimits) -> RunOutcome
```

Evidence receipts bind source-policy version/hash, target, snapshot/artifact hashes, field spans
and the real fetch attempt (or manual capture), so identical bytes can have a new actual observation
without inventing freshness from replay. `ChangeProposal` above is used only by the offline writer.
Add PageKind values `promo_index`, `partner_table`, `programme_news`, `feed`, and candidate kinds
for the three event types while preserving legacy `welcome_bonus`. Extend promotion mapping
explicitly with manual-safe defaults. Enum additions do not automatically authorize a backend;
unsupported page classes remain blocked until the existing fetch/config checks explicitly support
them under an approved source policy.

Argon owns C DTOs, event identity/validation and `ingestion/diff.py`; then stops writing and hands
Flash the exact SHA. Flash owns C writer/read repository, v6 migration/storage integration and
packaging/gate inclusion, then hands Luna public API/client/MSW and `/feed` UI work. Argon D owns
offline role contracts/processing in new `ingestion/feed_roles.py` and `feed_runtime.py`; Flash D
then owns CLI `ingestion/feed.py`, run receipts in `feed_storage.py` and timer handoff. Any shared
storage migration change is sequential. No separate incomplete core PR merges into main.

## Acceptance and limits

Builder supplies `python -m evals.demo_change_feed --data-dir <empty-scratch-dir>`: two labeled
retained fixture snapshots produce a supported event through scripted roles; separate-process
reopen/list returns the same ID, replay creates no duplicate/call, required bad quotes refuse,
correction preserves history, and retraction hides the public item. Assert unchanged seed hashes
and the transitive request-import boundary. Luna demonstrates the API/page in live local mode.
These commands are **required future deliverables, not executed or existing commands today**.
Run the existing complete gate on the finished feature. Real automated publishing still needs
source-display approval, the role-scope decision, applicable live budgets and real subject data;
the seven-night observation and real-model extraction are not proven by fixture acceptance.
