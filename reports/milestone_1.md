# Milestone 1 - deterministic rewards kernel

**Date:** 2026-07-24
**Status:** PASS

## Gate

- [x] Twelve optimizer golden cases pass.
- [x] Canonical demo output is byte-identical.
- [x] Two-run and all-golden determinism tests pass.
- [x] Property tests pass in the full suite.
- [x] `mypy --strict core/` is clean.
- [x] Float audit reviewed: only provenance confidence, geographic fields, docstring references, and ignored binary cache files matched; every money/points path remains integer-only.
- [x] Spec-01 Pydantic models and seeded SQLite facade are present.

## Test summary

- Python 3.14.6
- Optimizer golden selection: `12 passed, 8 deselected in 0.32s`
- Determinism selection: `3 passed, 17 deselected in 0.41s`
- Full pre-M1b suite: `20 passed in 0.42s`
- Strict type check: `Success: no issues found in 13 source files`
- Canonical demo diff: no output, exit code 0

## Float audit

Reviewed command:

```bash
grep -rn "float" core/optimizer core/models.py
```

Findings:

- `core/optimizer/allocate.py:59`: `min_confidence: float`, an aggregate provenance confidence, not money arithmetic.
- `core/optimizer/money.py:1`: docstring stating integer-only money primitives and no floats.
- `core/models.py:3`, `core/models.py:5`, `core/models.py:6`: module docstring explaining that money is not a float and listing allowed non-money float fields.
- `core/models.py:30`: `Provenance.confidence`, curator confidence only.
- `core/models.py:189` and `core/models.py:190`: `lat` and `lon`, geographic coordinates only.
- `core/models.py:241`: `centrality_score`, non-money POI ranking metadata.
- `core/models.py:332`: `confidence`, report provenance confidence only.
- Binary cache matches under `core/optimizer/__pycache__/` are ignored build artifacts, not source-code float usage.

## Deviations

See the M1 section of `DEVIATIONS.md`; no golden value was changed.
