# Recurring financial-offer ingestion — in progress

Branch `codex/recurring-offer-ingestion`, based on `d1f57101935e237594872b63d15afc3f81a49bf5` with `origin/main` as an ancestor. No production financial facts have been approved or published.

The existing durable Firecrawl acquisition, snapshot, review and controlled-apply services are present; the welcome catalog is separate and not yet wired to that review/apply path. The CLI currently does not expose its existing authorized extraction-client seam. Real automated extraction has not been demonstrated: no local Ollama service responded at `127.0.0.1:11434`, and no paid model call is authorized. Retained captures and scripted clients remain available for offline acceptance.

A focused synthetic regression now verifies optional, source-backed campaign start dates for historical and acquisition selection: dates outside a known validity period are excluded and overlaps or unknown starts stay ambiguous when multiple offers could apply. Existing rows without a published start keep their previous behavior. This does not deliver the recurring collection, review or publication workflow.

Current credit record: 67 of 500 used or reserved, 433 remaining. No Firecrawl scrape or model call has been made for this implementation. Full verification, integration, acceptance, final clean-tree gate and final commit are pending.

Focused verification so far: acquisition/ingestion baseline, welcome selection, welcome status and acquisition computations passed; the welcome and acquisition API checks passed with an explicitly seeded scratch `TRIPWISE_DATA_DIR`. Strict mypy for `welcome/` and focused Ruff passed. An initial API run without scratch storage hit a read-only SQLite path; the first scratch run was unseeded and failed; seeding the scratch database resolved both setup failures. No full gate has been run on this branch.

Still required: a durable combined lifetime Firecrawl budget; the scheduled entry point and explicit permitted real extractor; welcome-offer extraction and incomplete-draft handling; human review, controlled publication, catalog reload, version history and actual API consumption; all requested replay/change/failure/expiry demonstrations; and the required final gate. The absence of a local model is an activation limitation, not evidence that any of those remaining implementation tasks are complete.
