# Load test for the planning API

Runs the real FastAPI app with a fake LLM, so it measures the application and not a provider.
The fake LLM waits `BENCH_LLM_LATENCY` seconds per call, returns a fixed `TripSpec` for intake and
fails every other call, which sends the planner, critic and explainer down their deterministic
fallbacks. Set `BENCH_PROMPT_LOG` to a file path to record the prompt size of every call.

Run from `backend/` with the knowledge base seeded and at least `catalogs/active_sg-core.json` present.

```bash
export PYTHONPATH=scripts/loadtest:. BENCH_LLM_LATENCY=2
.venv/bin/uvicorn app_bench:app --port 8765 --workers 1 --log-level warning &
SERVER=$!
.venv/bin/python scripts/loadtest/drive.py $SERVER 1      # warm the catalog cache first
.venv/bin/python scripts/loadtest/drive.py $SERVER 100    # N simultaneous plans, polled every 1.5 s
.venv/bin/python scripts/loadtest/recompute.py            # /plan/recompute and /places/search throughput
kill $SERVER
.venv/bin/python scripts/loadtest/prof.py                 # where one warm plan spends CPU
```

`drive.py` reads `/proc/<pid>/status`, so it needs Linux. State files (databases, traces) are written
under `backend/`; point `TRIPWISE_DATA_DIR` at a scratch directory if you do not want that.

## Baseline, 2026-11-11

`origin/main` `a9efea0`, one uvicorn worker, 4 vCPU / 4 GB Linux VM, Singapore catalog, 2 s fake LLM.

| Simultaneous plans | Result | Poll latency p50 / p95 |
|---|---|---|
| 1 | complete in about 10 s | 10 ms / 12 ms |
| 25 | all complete in 12 s | 0.1 s / 1.9 s |
| 100 | all complete in about 24 s | 0.3 s / 18 s |
| 300 | 56 dropped connections, 1.6 GB peak, 341 threads | 57 s / 58 s |
| 25, cold catalog cache | server process died | n/a |

`/plan/recompute`: about 100 ms alone, about 10 requests/s ceiling; p50 5 s at 50 concurrent, 21 s at 200.

Prompt sizes for one plain plan, in characters (system + user): intake 3.0k, planner 12.4k,
critic 15.8k, explainer 1.5k.
