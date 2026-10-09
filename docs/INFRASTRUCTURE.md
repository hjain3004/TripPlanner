# Infrastructure and runtime boundaries

This page describes the implemented shape and the safe target seams. It is intentionally explicit
about disabled or planned pieces so a new model cannot mistake an adapter fixture for a live
provider.

## Request-time path

```text
Browser (Next.js + MSW by default)
        │  OpenAPI-shaped HTTP
        ▼
FastAPI API (`backend/api`)
        │
        ├── in-process job manager / bounded pipeline
        ├── `/plan/recompute` and `/plan/refresh-prose`
        └── `/places/search`
                │
                ▼
        Agents/orchestration
                │  typed values only
                ▼
        Deterministic kernel (`backend/core`)
```

The request-time default uses seeded/sample data and the configured LLM call sites. The kernel is
not allowed to import the gateway or reach the network. Provider I/O belongs behind
`backend/gateway/`; the orchestrator must map normalized evidence into kernel inputs.

## Gateway boundary

```text
Typed workflow
  ├─ travel registry ── SampleAdapter (enabled)
  │                    └─ Gondola (disabled by default; fixture/live seam)
  ├─ places registry ── sample/snapshot (enabled)
  │                    └─ Tripadvisor Terra (disabled by default)
  ├─ reference importers (offline commands)
  └─ evidence/catalog stores (provenance, freshness, lineage, cache/fixture rules)
```

The active profile is `student_noncommercial` with a hard zero-dollar external-spend ceiling.
Every enabled provider needs a reviewed registry entry, bounded budget, typed failure behavior,
source/freshness metadata, and a fallback. Installing an SDK or having a fixture does not activate
the provider. Booking, payment, points transfer execution, arbitrary URL fetches, dynamic MCP
discovery, and credentials in frontend/LLM context are outside the boundary.

## Persistence and evidence

- The Kernel knowledge base is seed-oriented/read-oriented; it is not a request-time crawler
  store.
- Gateway evidence stores keep source, artifact, claim, lineage, freshness, and invariant data
  separate from approved financial facts.
- Raw/live provider content is not silently promoted into the financial knowledge base. Offline
  financial ingestion remains a future human-reviewed proposal/approval workflow under spec 05.
- Account and planning persistence is user-scoped and uses the existing SQLite/CAS/audit patterns;
  it is separate from gateway quote/cache evidence.

## Environment matrix

| Surface | Default | Explicit live mode |
|---|---|---|
| Frontend API | `NEXT_PUBLIC_API_MODE=mock`, MSW, no backend network | `NEXT_PUBLIC_API_MODE=live` with a reachable backend |
| Travel gateway | sample/fixture evidence | registry/kill-switch and profile checks required; Gondola remains disabled by default |
| Places gateway | sample/snapshot evidence | Tripadvisor requires explicit injected live transport, persistent billable ledger, and activation review |
| Financial ingestion | absent | no activation path exists on `main` |

## Package boundaries

The intended dependency direction is one-way: `core/` is deterministic and provider-free;
`agents/` coordinates workflows; `api/` exposes request-time contracts; `gateway/` owns external
evidence. The documentation task verifies the boundary structurally but does not alter imports.

The frontend crosses into the backend only through `contract/openapi.json` and the generated/API
facade. It does not import Python packages or compute financial values.

## Operationally important gaps

- `/plan` is not wired to Gondola; the gateway seam is proven separately.
- Full structured Gondola response capture and normalization proof remain open in the G3.2 report.
- Live Tripadvisor activation remains pending.
- The robust financial-ingestion document is a plan only; FI1/Crawl4AI/Firecrawl work is not part
  of this handoff.
