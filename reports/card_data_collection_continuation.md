# Credit-card collection continuation and discovery reopening correction

The original private collection's discovery database now reopens through the actual
`FinancialIngestionStore`. Missing issuer URLs remain unknown; stored candidate payloads
are unchanged. Supplied unsafe URLs remain refused. No schema migration is needed.

The correction is limited to the optional issuer-URL validator. Its regression first
reproduced both the persisted-null failure and rejection of an explicit null. The corrected
regression and existing FI0 suite pass; focused Ruff passes. The complete backend gate is
run after committing this change, with its log and outcome retained alongside the private
collection, rather than manufacturing a report-only commit/gate cycle.

The owner authorized collection from remaining US, Indian and UAE issuer sources using
at most **445 additional Firecrawl credits**, after the previous **55 credits**. Recharge
and paid overages were confirmed disabled. This is a ceiling, not a target. The continuation
uses the existing acquisition control, immutable snapshots, canonicalization, parsers and
review workflow. No financial decision, origin confirmation, KB apply, paid model call,
account application or public deployment is authorized by this task.

Captures, source-access outcomes, credit accounting, pending review packets and the gate
record remain outside Git in the owner's existing `card-data-bank-2026-11-25` collection.
Blocked sources remain blocked. Historical survey observations, current issuer captures,
rendered provider HTML and research notes stay distinct. Missing conditions are not zero.

The collection is not a claim of exhaustive or fully verified country coverage. Repository
seeds, goldens, frozen arithmetic, authoritative specs and the public API are unchanged.
