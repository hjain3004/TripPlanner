# FI1 — PDF parser process isolation

**Status: the PDF hard-cancellation limitation recorded in `reports/fi1_snapshot_core.md` is
closed for every ingestion PDF path, offline. This does not close the other FI1 live
blockers (see "Not closed").**

Branch `codex/fi1-pdf-process-isolation`, from `c925d98` (the tip of
`codex/fi2-extraction-validation`; see "Base").

## Problem

`ManualUploadBackend` normalized PDFs with `asyncio.to_thread(canonicalize_content, …)` under
`asyncio.wait_for`. A timeout returned a typed failure to the caller, but Python cannot
interrupt a thread, so the parser kept running (and holding memory/CPU) after the caller was
told it had timed out. Two other paths were worse: the Crawl4AI `tnc_pdf` branch parsed the
body **inline on the event loop with no deadline**, and `verify_evidence_span` opened the PDF
directly in-process.

## Every ingestion PDF entry path (inventory)

| # | Path | Before | After |
|---|---|---|---|
| 1 | `ManualUploadBackend.fetch` → PDF upload | thread + `wait_for` (timeout did not stop the parser) | `acanonicalize_content` → killable child under `request.timeout_seconds`; caller cancellation also kills it |
| 2 | `Crawl4AIBackend.fetch` → `tnc_pdf` | inline `canonicalize_content`, no deadline, blocked the loop | same async child path; a timeout is `FetchFailureKind.TIMEOUT` (retryable) |
| 3 | `ingestion.evidence.verify_evidence_span` (PDF spans; called by the unmodified `validation.py`) | direct `pdfplumber.open` | `runner.page_text` in a child; timeout/crash/garbage → `EvidenceVerificationError("PDF evidence could not be verified")` |
| 4 | `canonicalize_content` / `canonicalize_pdf` called directly | in-process | same child, blocking the calling thread for at most the deadline |

`pdfplumber` is named in exactly one module, `ingestion/pdf_worker.py` (a test asserts this).
No other module imports `subprocess`/`multiprocessing`, creates a subprocess, or passes
`canonicalize_content` to `to_thread` (AST tests). I grepped all of `backend/` (api, agents,
gateway, scripts, evals): no other caller of `pdfplumber`, `canonicalize_pdf` or
`verify_evidence_span` exists.

## Design

- **Launch.** `[sys.executable, "-I", "-c", <constant bootstrap>, <backend root>]`: an argv
  list, never a shell; the only variable parts are paths this process computed. `-I` ignores
  `PYTHON*` variables, user site and the working directory. The child environment is rebuilt
  from scratch (`PYTHONUTF8`, `PYTHONDONTWRITEBYTECODE`, a minimal `PATH`, `LANG`); stderr is
  discarded; stdin/stdout are pipes; `start_new_session=True` gives the child a private process
  group.
- **Protocol.** stdin: one JSON header line (`op`, limits, `data_len`) then exactly that many
  PDF bytes. stdout: exactly one ASCII JSON line. The worker reads the whole request before
  parsing, so a parent that writes first cannot deadlock.
- **Parity.** The worker imports the existing `_normalize_lines`, so canonical text is
  byte-identical to the old in-process result; page-limit, character-limit, parse-failure and
  missing-dependency outcomes keep their exact exception classes and messages.
- **Private reply channel.** The worker moves fd 1 aside and points stdout at `/dev/null`
  before parsing, replying through the private descriptor. Whatever the parser library prints
  can never corrupt the reply, and a helper process it spawns does not inherit the reply pipe.
- **Cleanup on every path.** In `finally`: SIGKILL the child's process group (pgid == pid;
  signalled unconditionally because asyncio may already have reaped the leader — surviving
  members keep the pgid reserved, an empty group just raises ESRCH), then wait for the child
  so it is reaped, close the pipes, and release the concurrency slot. This runs on success,
  typed errors, deadline, parser crash, malformed reply, pipe overflow and `CancelledError`
  (including a second cancellation during cleanup, where the bookkeeping is cleared by a
  shielded waiter). The worker also ends its own group after replying — only when it leads
  both its group and its session, as the runner makes it — so a helper cannot outlive a
  normal exit.
- **Bounds.** Input ≤ the caller's `max_bytes` (hard ceiling 64 MiB); reply ≤
  `12 × max_chars + 4 KiB` (page text ≤ 1 M chars; twelve bytes is an escaped astral
  surrogate pair); wall-clock deadline that **includes** waiting
  for a slot; at most 2 children alive at once, shared by sync and async callers. A request
  that cannot get a slot before its deadline raises `TimeoutError` without launching anything.
  The reply line ends the wait (no dependence on EOF), and a reply without a trailing newline,
  non-JSON, wrong-shaped or oversized is `UnsupportedContentError("PDF could not be parsed
  safely")`.
- **No late writes.** The worker has no path, URL or file input and opens no files; its only
  output is the bounded reply the parent validates. Artifact and snapshot writes happen in the
  caller *after* the runner returns, so a timed-out or cancelled parse cannot reach them.

## What process isolation guarantees, and what it does not

**Guarantees** (each demonstrated against real processes, below): a hung or busy parser is
killed even if it ignores SIGTERM; the child is reaped (no zombie); a grandchild the parser
spawned in the worker's process group dies with it; a cancelled or timed-out parse produces no
result, no stored artifact, and no parent-visible output after the deadline; concurrent requests
never exceed the bound; a failing request releases its slot. A descendant that deliberately
creates a new session is outside process-group cleanup and is not claimed to be contained.

**Does not guarantee:**
- **It is not an OS security sandbox.** The child runs as the same user with the same
  filesystem, network and environment-derived access as the backend. A parser exploit could
  read files or open sockets before the deadline. Containers/seccomp/jails are separate work.
- No CPU or memory limits (`rlimit`) are set; only wall-clock time and pipe sizes are bounded.
- POSIX only (`killpg`, new sessions); Windows is unsupported by this module.
- The unconditional group kill has one theoretical window: after every member of the group is
  gone, a recycled pid that became a group leader could be signalled. It is microseconds wide
  and was not reproducible; it is accepted and documented rather than hidden.
- On a reap timeout (a process stuck in uninterruptible sleep) the slot is released but the
  pid stays listed in `live_count()`, so the "at most N children" bound is a bound on healthy
  children, not a promise about unkillable ones.
- The sandbox-adjacent edge: `sys.path` for the child gets the backend root *appended*, so its
  top-level package names cannot shadow installed modules.
- The synchronous entry points (`canonicalize_content`, `verify_evidence_span`) still occupy
  the calling thread for up to the deadline; they cannot be cancelled from outside because a
  thread cannot be, though the child is killed at the deadline.
- One child is started per PDF evidence span during validation (about 50 ms of interpreter
  start-up each); acceptable for the volumes involved, and batched verification is possible
  later if it matters.

## Verification

Tests are in `backend/evals/test_fi1_pdf_isolation.py` (82), written first and run red (the
import of the missing module failed collection) before the implementation existed. They use a
**synthetic `pdfplumber` double** (`ingestion/fixtures/pdf_double/pdfplumber.py`) whose behaviour
is chosen by the document bytes, driven through real child processes:

| Area | What is proven (sync and async where applicable) |
|---|---|
| Parity | multi-page success equals `_normalize_lines` of the same text (NFKC ligature included); empty text; page limit and character limit raise the same typed errors/messages; parser exception → same generic error; missing optional dependency → same error; crash and SIGSEGV → generic error and a reaped child |
| Termination | `hang-sleep`, a CPU-bound `hang-busy` loop and a parser that ignores SIGTERM are all killed at the deadline; the pid is checked from outside with `kill(pid, 0)` (a zombie would still answer, so this also proves reaping); a spawned grandchild dies; a parser that would write a file after the deadline never does (marker absent after waiting past its delay); caller cancellation kills the child, the grandchild and the late write; a helper holding the pipe neither delays the reply nor survives |
| Bounds | oversized input refused before any process exists; a worker flooding stdout is cut off and killed; six malformed/empty/spoofed replies are rejected; a worker that never reads stdin cannot block the writer past the deadline (12 MB input); peak live children ≤ 2 under six concurrent requests (threads, and one event loop); a waiter respects its deadline and starts nothing; a failed request releases its slot |
| Entry paths | `canonicalize_content`/async twin; manual upload success, page-limit failure (`invalid_response`), timeout (`timeout`, **zero artifacts stored**, child gone) and cancellation (zero artifacts, child gone); Crawl4AI `tnc_pdf` success and timeout (zero artifacts, bounded time); evidence verification success, wrong page, out-of-range page, and a hung PDF failing closed within the deadline |
| Source guards | the parser library is named only in the worker; process creation is confined to `pdf_isolation.py`; no shell; no `to_thread(canonicalize_content …)` outside `canonical.py`; fixed-argv launch |

**Test teeth.** Eighteen mutations were applied one at a time and each is killed by a test:
group kill removed; reaping skipped; sync and async slot bounds removed; reply bound removed;
async cleanup never kills; async skips the group kill once asyncio reaped the leader (the bug
the review found); worker keeps its group; worker kills any group it leads; worker stdout not
claimed; recursion not typed; expansion factor 6; cleanup bookkeeping outside `finally`;
reply line no longer ends the wait; PDFs routed back to a thread; Crawl4AI parses inline;
evidence swallows a timeout; input bound removed. Two mutants initially survived because the
review-driven private reply channel made those defenses redundant for the original scenario;
I added tests that exercise each directly (a worker that replies and then hangs; the worker's
own group cleanup run without any parent-side kill).
The timing-sensitive file passed repeated runs (≈28 s each) and the reviewer's parallel and CPU-loaded runs and leaves no process
behind (`ps` shows none after a run). An early mutation run left one orphaned test worker —
the expected effect of a mutant that does not kill — and I removed it by hand.

**Process notes.** `ruff format` on the whole package initially reformatted three files this
task must not touch (`validation.py`, `preflight.py`, `migrations.py`); they were restored
from the base commit and the diff against `c925d98` lists only the intended files.

## Independent review

One fresh-context read-only reviewer reproduced each finding with a script. It found **no
Critical** issues, confirmed the diff touches only the intended files (`parsing.py`,
`extraction.py`, `validation.py`, storage, travel, API/OpenAPI, frontend, specs, seeds and
goldens untouched; no other PDF path bypasses the runner), and ran 150 random-time
cancellations with no leaked slot, child or warning. Findings and dispositions:

| # | Severity | Finding (reproduced) | Disposition |
|---|---|---|---|
| 1 | Important | Async path skipped the group kill once asyncio had already reaped a crashed worker, so a helper it spawned survived (sync did not) | **Fixed** — pgid is killed unconditionally; the reply channel is private so the helper no longer holds the pipe; regression in both modes |
| 2 | Important | A deeply nested reply raised a raw `RecursionError` out of `fetch` | **Fixed** — typed `UnsupportedContentError`; regression with a 200 000-deep reply |
| 3 | Important | Large parser chatter on stdout turned a good parse into "could not be parsed safely" | **Fixed** — worker claims fd 1; regression with 3 000 noisy lines |
| 4 | Minor | JSON expansion factor 6 was wrong for astral characters (1 000 emoji failed) | **Fixed** — factor 12; regression |
| 5 | Minor | A second cancellation during cleanup left a stale `live_count()` | **Fixed** — bookkeeping cleared by a shielded waiter; regression |
| 6 | Minor | The worker's own group kill also hit a group it merely led inside someone else's session | **Fixed** — also requires session leadership; regression with a sibling process |
| 7 | Minor | `BlockingIOError` on read; unbounded `spawned_pids`; bootstrap `sys.path.insert(0)` | **Fixed** (handled; capped at 4 096; appended) |
| 8 | Minor | Sync entry points block their thread up to the deadline; reap timeout leaves a pid listed; evidence now fails closed above 64 MiB / 1 M page chars; request-derived reply bound | **Accepted and documented** above and in DEVIATIONS (all current callers are synchronous; none blocks an event loop) |
| 9 | Minor | Test gaps (cancellation during cleanup, helper after crash, astral bound, noise, nesting); two timeout tests could pass if the child had not started | **Gaps filled** with the regressions above; the timeout headroom (0.4 s vs ≈50 ms start-up) held under CPU load |

## Verification evidence

- Own seeded baseline at `c925d98` (`make seed`, regional catalogs present,
  `TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1`): **2231 passed, 1 skipped** (2232 collected without
  the new file).
- Focused PDF/FI regressions (`test_fi1_pdf_isolation.py` 82, `test_fi0_ingestion.py`,
  `test_fi1_snapshot_core.py`, `test_fi2_extraction.py`): all pass.
- Full backend suite after the review fixes: **2313 passed, 1 skipped** (2231 + 82).
- `mypy --strict` over `core/ accounts/ planning/ agents/ api/ gateway/` and `ingestion/`, and
  `ruff check` over the zero-tolerance scope: clean (final numbers in the hand-off message).
- `make gate` on the exact committed clean tree: result and commit hash are in the hand-off
  message (a report cannot contain its own commit hash).

## Not closed

- **Not an OS sandbox** (see above).
- The real `pdfplumber` was **never executed**: it is an optional extra not installed in this
  environment, and nothing was installed. The worker's call surface (`pdfplumber.open(BytesIO)`,
  `.pages`, `.extract_text()`) is exactly the one the old in-process code used, but parity with
  the real library is established only through the double. A one-off supervised run with the
  `ingestion-local` extra on a real PDF is still required before live use.
- The other FI1 live blockers remain: a durable cross-process delay ledger, a
  scheduler/worker deployment, and live Crawl4AI acceptance. No crawling was activated.
- No resource limits (CPU/memory), no Windows support, no batching of per-span verification.

