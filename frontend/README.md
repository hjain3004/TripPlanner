# TripPlanner Frontend

Next.js 16 app powering the TripPlanner frontend.

## Environment matrix

| Environment | `NEXT_PUBLIC_API_MODE` | `NEXT_PUBLIC_API_BASE_URL` | MSW | Network |
|---|---|---|---|---|
| **Dev** | `mock` (default) | — | Intercepts all API requests | Off by default |
| **Dev** | `live` | `http://localhost:8000` | Off | Real backend on port 8000 |
| **Preview** | `mock` (default) | — | Intercepts all API requests | Off by default |
| **Preview** | `live` | `<deployed-backend-url>` | Off | Real backend |
| **Production** | `mock` (default) | — | ServiceWorker can be disabled by user; falls through to network if not registered | Off by default |
| **Production** | `live` | `<deployed-backend-url>` | Off | Real backend |

- `NEXT_PUBLIC_API_MODE=mock` (default): MSW ServiceWorker intercepts all requests to the API base URL. No network calls are made to the backend.
- `NEXT_PUBLIC_API_MODE=live`: MSW is disabled. All requests go to `NEXT_PUBLIC_API_BASE_URL`. The backend must be running and reachable.

## Setup

```bash
npm install
npm run dev
```

Gates:

- `make gate-f1` — design tokens, contrast, types, build, e2e (primitives + aXe)
- `make gate-f2` — wizard e2e + contract tests
- `make gate-f3` — results page e2e + no-orphan-numbers + contract
- `make gate-f4` — bundle check + performance + regression on f1–f3
- `make gate-f1 gate-f2 gate-f3 gate-f4` — full frontend regression

See `Makefile` and `AGENTS.md` for details.
