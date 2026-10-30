# PDF process isolation against the real `pdfplumber`

This report has two parts. They cover **different revisions**; do not read the historical
results as evidence about current `main`, or the other way round.

| Part | Revision exercised | Branch |
|---|---|---|
| **1. Main-based closure (current)** | base `6f0859b146f69d0a6f55e3a3c9ac1146353f455e` (`origin/main`, PR #20 merge) + this branch's commit | `codex/pdf-compatibility-closure` |
| 2. Historical verification | base `18eda70f06f29b29de4006b7fc784a16e606cba0` (tip of `codex/fi1-pdf-process-isolation`) + `b4511fb` | `codex/pdf-real-library-verification` (preserved, unmodified) |

**Neither part establishes exploit resistance, and the process boundary is not an OS sandbox.**
Benign, generated PDFs can show compatibility only; they cannot show that a crafted PDF fails to
exploit `pdfminer.six`, Pillow or pypdfium2. The worker runs as the same user with the same
filesystem and network access and no memory/CPU rlimits; it bounds time, output and cleanup only.

---

## 1. Main-based closure (`codex/pdf-compatibility-closure`)

**Result:** with the real `pdfplumber` installed, a generated PDF goes through the current
production isolation path (`get_default_runner()`, `canonicalize_content`,
`acanonicalize_content`, `verify_evidence_span`) and produces the same text, errors and
page-specific evidence decisions as the previous in-process code. The one demonstrated defect —
an environment-dependent missing-dependency test — is fixed in the test. **No production file was
changed**; none was needed, because no production defect was reproduced.

### Changes on this branch

| File | Change |
|---|---|
| `backend/evals/test_pdf_real_library_compatibility.py` | Ported byte-for-byte from `b4511fb` (file content only; the old base was not merged). It ran unmodified against current `main`'s `ingestion/` APIs. |
| `backend/evals/test_fi1_pdf_isolation.py` | `test_a_missing_optional_dependency_is_the_same_typed_error` now simulates absence **inside the child** (see below). Nothing else in the file changed. |
| `reports/pdf_real_library_compatibility.md` | This report. |

### The fixed defect

Reproduced on unmodified `origin/main` (`6f0859b`) with the real library installed:
`test_fi1_pdf_isolation.py` → **2 failed, 81 passed**; the failures were
`test_a_missing_optional_dependency_is_the_same_typed_error[sync|async]`. The test used a runner
with no search path and *assumed* the interpreter lacked `pdfplumber`; where the optional
dependency is installed the worker parses (or rejects) the bytes instead of reporting absence.

Fix: the test writes a `pdfplumber.py` into `tmp_path` that raises
`ModuleNotFoundError("No module named 'pdfplumber'", name="pdfplumber")` and passes that
directory through the existing parent-constructed `--search-path` seam
(`PdfProcessRunner(search_paths=[...])`, already the documented FI1 test seam). The worker inserts
it at `sys.path[0]` in the real child process, so the production statement
`__import__("pdfplumber")` in `ingestion/pdf_worker.py` raises `ImportError` there, the worker
replies `missing_dependency`, and the parent maps that to the existing
`UnsupportedContentError("… optional ingestion-local extra")`. The assertion is unchanged (same
type, same message match) and is strengthened: exactly one child was spawned, none is live, and
its pid is gone (reaped). No skip was added; production behaviour is untouched.

### Environment (recorded from this run)

| | |
|---|---|
| Platform | macOS 26.6.1, arm64 |
| Python | CPython 3.14.6 (Homebrew), both environments |
| `pdfplumber` | **0.11.10** (declared `pdfplumber>=0.11,<1`; checked by a test against `pyproject.toml`) |
| `pdfminer.six` | 20260107 |
| `Pillow` / `pypdfium2` / `cryptography` | 13.0.0 / 5.14.0 / 50.0.2 |
| `pytest` / `pydantic` / `packaging` | 9.1.1 / 2.14.1 / 26.3 |

Environments were **reused, not created** (host had ~1 GiB free; nothing was installed):

- **Without the dependency:** the primary checkout's full project venv
  (`/Users/himanshu_jain/TripPlanner/backend/.venv`, no `pdfplumber`), symlinked as this
  worktree's `backend/.venv` like the other task worktrees. This is also the gate interpreter.
- **With the dependency:** the existing task-owned
  `.superpowers/pdf-real-venv` from the historical verification worktree (pinned test subset plus
  `pdfplumber` and its dependencies; no Crawl4AI, no browser runtime). Used read-only, run from
  this worktree's `backend/` so the code under test is this branch's.

### Checks run on this branch (measured)

| Check | Interpreter | Result |
|---|---|---|
| `test_fi1_pdf_isolation.py` on unmodified `main` | with `pdfplumber` | 2 failed, 81 passed (the reproduced defect) |
| Fixed `-k missing_optional` (sync + async) | with `pdfplumber` | 2 passed |
| Fixed `-k missing_optional` (sync + async) | without | 2 passed |
| `test_pdf_real_library_compatibility.py` + `test_fi1_pdf_isolation.py` | with `pdfplumber` | **134 passed** (51 + 83) |
| Same two modules | without | **83 passed, 51 skipped**, every skip reporting "real pdfplumber is not installed in this interpreter…" |
| `test_fi0_ingestion.py`, `test_fi1_snapshot_core.py`, `test_fi2_extraction.py` | with `pdfplumber` | 53 passed |
| `ruff check` + `ruff format --check` on both test files | without | clean |
| Worker processes left after the runs (`ps`) | — | 0 |

The full backend gate (`make gate`) is run on the exact committed tree, in the environment without
the optional dependency, as the acceptance check; its result is recorded with the commit hand-off,
not pre-written here.

### What the real-library run demonstrated on `main`

The 51 ported tests exercised, through the production worker with no search path: the child
resolving `pdfplumber` from `site-packages` (never the double) under `-I` with a rebuilt
environment; eight generated single/multi-page, blank, Flate, Unicode/NFKC, paragraph and spacing
documents canonicalizing identically to the copied previous in-process implementation (and to
pinned exact strings), sync and async; page-specific evidence verification via
`verify_evidence_span` with the default runner (right page accepted on pages 1–3, wrong page,
out-of-range page and blank-page claims rejected, a truncated raw PDF failing closed); page,
character, reply and input-byte limits; fourteen corrupt/truncated inputs matching the previous
outcome with typed failures; deadline, cancellation, concurrency bound and no-surviving-worker
checks. Details of each are in Part 2, which these tests reproduce on the newer base.

### Remaining limitations

Everything under Part 2's "Not verified" still applies: Latin/WinAnsi Helvetica only (no
embedded/subset fonts, CJK, RTL, emoji); no encrypted, object-stream, scanned, form or real issuer
T&C PDFs; the 1 M-character page bound and large-input performance not driven; macOS arm64 only
(Linux deployment target not run); floating `pdfplumber`/`pdfminer.six` versions within the
declared range; and **no claim of exploit resistance or OS sandboxing**. The optional dependency is
not in the gate environment, so the real-library module is skipped by `make gate`; it must be run
explicitly with an interpreter that has the library.

---

## 2. Historical verification (`codex/pdf-real-library-verification`, base `18eda70`)

*Preserved as recorded. These results describe base `18eda70` + `b4511fb`, not current `main`.*

**Result: compatibility demonstrated for benign, generated PDFs. No production defect found.
No production file, shared test, dependency declaration, lockfile, spec, seed, golden, OpenAPI
or frontend file was changed.** The only repository additions were
`backend/evals/test_pdf_real_library_compatibility.py` (51 tests) and this report.

### Exact environment (recorded, not assumed)

| | |
|---|---|
| Python | 3.14.6 (Homebrew), macOS 26.6.1, arm64 |
| `pdfplumber` | **0.11.10** — resolved from the declared requirement `pdfplumber>=0.11,<1` |
| `pdfminer.six` | 20260107 |
| `Pillow` / `pypdfium2` | 13.0.0 / 5.14.0 |
| `cryptography` / `cffi` / `charset-normalizer` | 50.0.2 / 2.1.1 / 3.5.2 |
| `pytest` / `pydantic` / `packaging` | 9.1.1 / 2.14.1 / 26.3 |

Two task-owned virtualenvs (neither is shared; neither alters project declarations):

- **A** `backend/.venv` — the project's pinned test packages only, **no `pdfplumber`**. This is
  how the existing suite is designed to run.
- **B** `.superpowers/pdf-real-venv` (gitignored) — the same pinned packages **plus** the declared
  `pdfplumber` and its dependencies. Nothing else from the `ingestion-local` extra (no Crawl4AI,
  no browser runtime) was installed.

`pdfplumber` is not in `requirements*.lock` (it is an optional extra), so its version floats within
the declared range; the versions above are what this run resolved. Part-way through, the host disk
filled up and a first install silently failed; after space was freed the environments were
re-created and every result below comes from the re-run. The dev lock was installed only as the
hash-pinned subset these tests import (pytest, pydantic, pyyaml, hypothesis, httpx and their
direct pins) because the full lock (pandas, ortools, mypy, …) was unnecessary for PDF tests.

### Evidence the worker used the installed library

Each of these is an executed assertion in the new module:

1. A diagnostic child launched with the **production configuration** (same interpreter, `-I`,
   the runner's rebuilt environment) imports `pdfplumber` from
   `…/pdf-real-venv/lib/python3.14/site-packages/pdfplumber/__init__.py` (version 0.11.10) and
   `pdfminer` from `site-packages`; `ingestion.pdf_worker` resolves to the repository file; and
   no `sys.path` entry contains `pdf_double`.
2. The production runner has no `--search-path` argument (the only seam that can place the double
   on the path), and its argv still begins `[sys.executable, "-I", "-c"]`.
3. **Behavioural proof.** The real library parses the generated PDFs through the isolated worker,
   and rejects the double's `%PDF-DOUBLE` bytes with the generic typed error. Negative control
   (run by hand): a runner deliberately given the double's directory parses the *real* PDF as
   `UnsupportedContentError` while the previous in-process code returns the text — so a shadowed
   import would make the parity tests fail, not pass.
4. The installed version is checked against the specifier read from `pyproject.toml`.
5. The child environment is rebuilt: a parent `PDF_VERIFY_CANARY` and a hostile `PYTHONPATH` do not
   reach it, and `sys.flags.isolated == 1`.

### What was run and what passed

| Run | Interpreter | Result |
|---|---|---|
| New: `test_pdf_real_library_compatibility.py` | B (real `pdfplumber`) | **51 passed**, repeated 4 times (≈7–9 s each), no flake |
| New module where the library is absent | A | **51 skipped**, each with the reason "real pdfplumber is not installed…" (never a silent pass) |
| Existing `test_fi1_pdf_isolation.py` (synthetic double) | A | **82 passed** (28 s) |
| Existing `test_fi0_ingestion.py`, `test_fi1_snapshot_core.py`, `test_fi2_extraction.py` | A | **45 passed** |
| Existing `test_fi1_pdf_isolation.py` | B | 80 passed, **2 failed by construction** — see Findings |
| `ruff check` + `ruff format --check` on the new file | A | clean |
| Worker processes left after every run | — | **0** (`ps` after each run; each test also asserts its runner's live count is 0 and each recorded pid is gone, so a zombie would fail it) |

#### Coverage of the requested areas (all executed in B)

- **Single- and multi-page canonicalization** — 8 generated documents (single page; single page with
  Flate-compressed content; three pages; blank middle page; all-blank; Unicode; a 40-line
  paragraph page of ~2.9 k characters; spacing/tab/blank-line collapse). For each, the isolated
  result **equals** the previous in-process implementation, whose code is copied verbatim from
  base commit `c925d98` into the test as the reference. Exact expected strings are also pinned, so
  two identically wrong answers could not pass. Async path checked on three of them.
- **Page-specific evidence verification** — `verify_evidence_span` through the production runner
  (nothing injected): correct page passes for pages 1–3; the wrong page → "not present on the
  cited page"; page 9 → "outside the artifact"; a quote claimed on a blank page is rejected; a
  truncated raw PDF → "could not be verified" (fails closed). `runner.page_text` equals the
  previous per-page extraction for every page of four documents, and the out-of-range page is
  typed.
- **Blank pages and Unicode** — blank pages extract as empty and contribute nothing; accented
  Latin, em dash, euro, curly quotes and bullets pass through unchanged; NFKC runs exactly as
  before (`m²`→`m2`, `™`→`TM`, `½`→`1⁄2` with the fraction slash, `ª`→`a`).
- **Limits** — page limit (`PDF exceeds 2 page limit`, and exactly-at-limit succeeds); character
  limit boundary (equal passes, one less is `ContentLimitError`, both identical to the previous
  behaviour); the reply bound with a realistic ~2.9 k-character page at the tightest legal
  `max_chars`; input-byte bound (refused with no process started at `len-1`, accepted at `len`).
- **Corrupt and truncated input** — 14 damaged inputs (empty, plain text, header only, header+EOF,
  2 KiB of seeded random bytes, HTML in disguise, truncations at 10 %, 33 %, 90 %, cut at `xref`,
  last 20 bytes removed, smashed header, zeroed middle, garbage appended). Every outcome equals
  the previous in-process outcome, and every failure is the typed
  `UnsupportedContentError("PDF could not be parsed safely")`. Ten of the fourteen are failures,
  so the corpus is not vacuous; the other four are cases where the **real library recovers** (see
  Findings). Async path checked on two.
- **Isolation with the real library loaded** — a 20 ms deadline fires while the real `pdfplumber`
  is still importing: `TimeoutError`, worker killed and reaped, runner reusable afterwards; caller
  cancellation of a real parse kills the worker; six concurrent real parses never exceed the bound
  of 2 children and all return the right text; mixed successful/failed runs leave no worker.

### Findings

1. **No production defect.** Output, error classes and messages were identical to the previous
   in-process real-library behaviour in every comparison.
2. **Two existing tests are environment-dependent (not a production defect).**
   `test_a_missing_optional_dependency_is_the_same_typed_error[sync|async]` in
   `test_fi1_pdf_isolation.py` asserts the "optional extra missing" message, so it fails whenever
   `pdfplumber` is installed. Reproduction: run `test_fi1_pdf_isolation.py` with environment B →
   2 failed, 80 passed (it passes, 82/82, in A). *Resolved in Part 1 on the main-based branch by
   simulating absence inside the worker; the historical branch itself was not edited.*
3. **The real library tolerates some damage, and the isolated worker matches it exactly.**
   Smashed header, a zeroed middle section, garbage appended, and the final 20 bytes removed are
   all *recovered* by `pdfminer` and return text identically in both implementations. That is
   library behaviour inherited unchanged, but it means "corrupt PDF" does not always mean "typed
   failure"; downstream code must treat extracted text as untrusted either way.
4. **Library warnings go to the child's discarded stderr.** `pdfminer` logs lines such as "Could
   not get FontBBox…" for damaged input. In the isolated worker these are discarded (stderr is
   `/dev/null`), so unlike the old in-process code they no longer appear in the parent's logs; a
   behaviour difference in diagnostics only.

### Not verified (stated plainly)

- **Fonts and scripts.** Fixtures use the standard Helvetica font with WinAnsi encoding. Embedded
  or subsetted fonts, CJK, right-to-left text, emoji and ligature-bearing fonts were not tested,
  so "supported Unicode" means the Latin/WinAnsi range above.
- **PDF features.** Encrypted PDFs, object/xref streams, scanned (image-only) pages needing OCR,
  forms/annotations, very large or many-page documents, and tables were not exercised. Real
  issuer T&C PDFs (the actual target) were not used — none was fetched or generated.
- **The 1 M-character page-text bound** (evidence path) and very large inputs were not driven
  with the real library; performance and memory under real-world PDFs are unmeasured.
- **Hostile input.** A benign parse cannot show resistance to a crafted PDF that exploits
  `pdfminer`, Pillow or pypdfium2. The process boundary bounds time and cleanup; it is not a
  sandbox (same user, filesystem, network, no rlimits).
- **Platforms.** Only macOS arm64 with CPython 3.14.6. Linux (the likely deployment) was not run.
- **Floating dependency versions.** Results hold for the versions recorded above; a newer
  `pdfplumber`/`pdfminer.six` could change extraction. The comparison to the previous behaviour
  uses the same installed library in both arms, so it detects *isolation* drift, not library drift.

---

## Fixtures and rights

No binary fixture is stored. Every PDF is produced at test time by `build_pdf` in the test module
(about 30 lines; a hand-written PDF 1.4 object/xref writer using the built-in Helvetica font), from
synthetic strings written for this test. There is no third-party content, so there is nothing to
license or redistribute; the bytes are deterministic (the random corruption uses a fixed seed).
The missing-dependency shadow module is written to pytest's `tmp_path` at test time and never
committed.

## How to reproduce

```bash
cd backend
# Without the optional dependency (the gate environment): real-library module is skipped.
.venv/bin/pytest -q -rs evals/test_pdf_real_library_compatibility.py evals/test_fi1_pdf_isolation.py
# With it: any interpreter that has the project's test packages plus "pdfplumber>=0.11,<1".
/path/to/pdf-venv/bin/python -m pytest -q evals/test_pdf_real_library_compatibility.py evals/test_fi1_pdf_isolation.py
```
