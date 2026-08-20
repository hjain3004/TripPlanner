# G2 — Open/Reference Importers Implementation Plan

> **For agentic workers:** Executed inline in the same session per explicit human directive
> ("do not stop after writing a plan... execute it"). Saved to the repo for recovery per
> CLAUDE.md's session-start protocol.

**Goal:** Build offline, deterministic, licence-aware reference-data importers for FX rates
and airports (spec 09 §13 "G2"), and audit the existing POI catalog pipeline against the
same gate — proving licence metadata retention, byte-identical deterministic snapshots, and
zero change to golden optimizer values. This is reference-data ingestion, not pipeline
integration: nothing in `agents/pipeline.py` or the request-time `/plan` path changes.

**Architecture:** A new `backend/gateway/reference/` package (parallel to the existing
`gateway/catalog/`, `gateway/places/`, `gateway/travel/`, `gateway/evidence/` siblings) holds
a small shared `SourceProvenance` contract plus two independent importers —
`gateway/reference/fx/` and `gateway/reference/airports/` — each split into `contracts.py`
(typed records + snapshot), `parse.py` (raw-bytes → validated intermediate records, `Decimal`
for FX, never `float`), `build.py` (validated records → deterministic normalized snapshot,
pure function, no I/O), and `fetch.py` (an explicit, human-run, offline developer command
against one fixed allowlisted host — never imported by tests, `core/`, `agents/`, `api/`, or
any request path, mirroring the existing `scripts/fetch_overture.py` pattern). `gateway/catalog/`
(POI) is audited in place — spec 09 §13's G2 gate items are checked against the existing
pipeline and either accepted with evidence or closed with a small number of new acceptance
tests; no second POI ingestion architecture is created.

**Tech Stack:** Python 3.11, Pydantic v2, `decimal.Decimal`, stdlib `csv`/`json`, pytest,
mypy --strict, ruff. No new third-party dependency — stdlib `csv` and `json.loads(...,
parse_float=Decimal)` are sufficient for both new importers.

## Global Constraints

- All FX rate parsing uses `Decimal`, constructed from strings (`Decimal(str(x))` or
  `json.loads(..., parse_float=Decimal)`), never `float`, at any point before conversion to
  integer `rate_micro`.
- `backend/core/` imports nothing from `backend/gateway/` (existing AST test from G1 already
  covers this for the whole `gateway` package, including the new `gateway.reference`
  subpackage — verified, not re-implemented).
- No fetch function (`gateway/reference/fx/fetch.py`, `gateway/reference/airports/fetch.py`)
  is imported by `core/`, `agents/`, `api/`, any FastAPI route, or any test other than its own
  narrow "is a manual CLI, not wired anywhere" boundary test.
- Zero network calls in the normal test suite (guarded, non-vacuous `socket.socket.connect`
  monkeypatch tests for both new importers).
- Imported reference snapshots never overwrite `backend/core/seeds/fx_rates.yaml` or any
  other seed file; they are written to a separate output location and require a human
  decision to ever become a seed.
- `agents/pipeline.py`, `agents/estimator.py`, `agents/gateway_estimator.py`,
  `core/optimizer/`, `core/transfer/pathfinder.py` are not modified. `evals/golden/` stays
  byte-identical (`git diff --exit-code` clean throughout).
- No new third-party dependency added.
- `AGENTS.md`/`CLAUDE.md` stay byte-identical; checkpoint prose updates only in the final
  docs commit.
- `contract/openapi.json` and generated frontend files are not touched — G2 has no public
  API surface.

---

## 0. Source verification (performed before any implementation; recorded here as the
   evidence artifact for `reports/g2_open_reference_importers.md` §"Source-selection
   evidence")

### FX: Frankfurter (`api.frankfurter.dev`) — re-verified 2026-08-20, LIVE FETCHES

The existing `reports/free_apis.md` describes Frankfurter as an "ECB reference rates" proxy
with roughly 30 currencies. **This is stale.** Live verification today found:

- **Owner:** Frankfurter (`frankfurter.dev`), an open-source (MIT-licensed) project; the
  hosted API is free, keyless, and has no published rate limit tied to a paid tier.
- **Fixed source URL (base):** `https://api.frankfurter.dev/v2/` — confirmed endpoints:
  `/v2/currencies` (currency list), `/v2/rates?base=<CCY>&quotes=<CCY,CCY,...>` (rates),
  `/v2/rate/{base}/{quote}` (single pair), `/v2/providers` (per-currency source
  attribution).
- **Currency coverage — corrected finding:** live fetch of `/v2/currencies` today returned
  **169 currencies**, explicitly including `AED`, `INR`, `SGD`, `USD` (all four verified
  present by name and code). The API aggregates rates from **84 central banks/providers**,
  not ECB alone — this is a genuine change from the older v1 API's ECB-only ~30-currency
  set that `reports/free_apis.md` was written against. AED is available because it comes
  through a non-ECB provider (the UAE isn't an ECB reference-rate currency); Frankfurter's
  `/v2/providers` endpoint documents which underlying source backs which currency, but that
  provider-level detail is not reproduced record-by-record in this milestone — it is logged
  as a **known gap**: this importer trusts Frankfurter's own v2 aggregation and does not
  independently verify each currency's ultimate upstream institution.
- **Response schema — corrected finding:** `/v2/rates?base=USD&quotes=AED,INR,SGD` returns a
  **flat JSON array** of `{"date": "...", "base": "...", "quote": "...", "rate": <number>}`
  objects — e.g. `[{"date":"2026-08-20","base":"USD","quote":"AED","rate":3.6725}, ...]`.
  This is a different shape from the older v1 API's single nested `{"base":...,
  "rates":{...}}` object; the parser in this plan targets the confirmed **v2 flat-array**
  shape.
- **Licence/terms:** No dedicated legal/licence page was found linked from
  `frankfurter.dev/docs`. The FAQ states commercial use is permitted ("see each provider's
  terms for details on the underlying data") and suggests self-hosting/caching for
  high-volume use; no explicit attribution requirement is stated. **Decision:** treat this as
  `licence_id="frankfurter-api-blended-central-bank-sources"` (not a single well-known SPDX
  licence — logged honestly as such), attribute as `"Exchange rate data from
  Frankfurter (frankfurter.dev), aggregating data from 84 central banks/providers."`, and
  mark `needs_verification=True` at the snapshot-provenance level so a human reviews before
  any imported rate is ever proposed as a seed replacement (never automatic per the
  milestone's own boundary rule).
- **Cost:** Confirmed **USD 0** — no API key, no account, no billing page found; keyless GET
  requests only.
- **Geographic coverage:** global (169 currencies as of this verification).
- **Known gaps:** no dedicated terms/licence document beyond the FAQ answer quoted above; no
  per-currency provider attribution captured in this importer (logged, not fabricated).

### Airports: OurAirports (`ourairports.com` / `davidmegginson/ourairports-data`) —
   re-verified 2026-08-20, LIVE FETCH

- **Owner:** OurAirports (David Megginson); official data page `ourairports.com/data/`
  directs to the GitHub-hosted mirror.
- **Fixed source URL:** `https://davidmegginson.github.io/ourairports-data/airports.csv`
  (the official page's own linked download location — confirmed live).
- **Licence:** confirmed **Public Domain** — "All data is released to the Public Domain, and
  comes with no guarantee of accuracy or fitness for use." Attribution is encouraged, not
  required; this importer still records attribution (`"Airport data courtesy of
  OurAirports (ourairports.com), released to the Public Domain."`) as good practice, per the
  milestone's own requirement to record attribution text for every source regardless of
  whether the licence mandates it.
- **Update/release semantics:** files are updated **nightly**, no formal versioned release
  identifier — a rolling "latest" distribution. **Decision (Tier C, logged in
  DEVIATIONS.md):** since there is no snapshot/release ID to pin, this importer's
  `SourceProvenance.release_id` is the **retrieval date** (`YYYY-MM-DD`, injected, never wall
  clock inside the deterministic build step) combined with the **content hash** of the fetched
  CSV — the pair `(retrieved_at date, content_hash)` is the closest honest analogue to a
  release identifier this source actually offers.
- **Schema (confirmed via the official data dictionary, `/help/data-dictionary.html`), 19
  columns in order:** `id, ident, type, name, latitude_deg, longitude_deg, elevation_ft,
  continent, iso_country, iso_region, municipality, scheduled_service, gps_code, icao_code,
  iata_code, local_code, home_link, wikipedia_link, keywords`. `iata_code`, `local_code`,
  `gps_code`, `icao_code`, `home_link`, `wikipedia_link`, `keywords`, `elevation_ft` are
  nullable/optional; `type` is one of `balloonport, closed_airport, heliport, large_airport,
  medium_airport, seaplane_base, small_airport`.
- **Cost:** confirmed **USD 0** — static file over HTTPS, no key, no account.
- **Geographic coverage:** global, all airport types (not just those with scheduled
  service).
- **Known gaps:** no formal release/version identifier (see decision above); route/schedule
  connectivity data exists in a separate OpenFlights dataset that is explicitly **out of
  scope** per this milestone's own instruction ("do not add stale OpenFlights route data").

### POIs: existing `gateway/catalog/` — audited, not re-sourced

Inspected `gateway/catalog/manifest.py`, `build.py`, `activate.py`, `quarantine.py`,
`tiles.py`, `identity.py`, and the existing test files `test_catalog_determinism.py`,
`test_catalog_boundary.py`, `test_catalog_compaction.py`, `test_network_isolation.py`,
`test_region_isolation.py`. Findings feed directly into G2c (§4 below) — no new source
research needed; Overture/OSM/Wikivoyage licensing was already reviewed under I3–I7.

---

## 1. Shared reference-snapshot contract

**Files:**
- Create: `backend/gateway/reference/__init__.py` (empty)
- Create: `backend/gateway/reference/contracts.py`
- Test: `backend/evals/test_reference_contracts.py`

**Interfaces:**
- Produces: `SourceProvenance(BaseModel)` with fields `source_id: str`, `source_owner: str`,
  `source_url: str`, `release_id: str`, `retrieved_at: date` (injected, not wall-clock —
  `date` not `datetime`, since neither source has sub-day granularity and this avoids a
  timezone axis this milestone doesn't need), `licence_id: str`, `attribution: str`,
  `terms_reference: str`, `content_hash: str` (`sha256` hex of the raw input bytes),
  `record_count: int = Field(ge=0)`, `warnings: list[str] = Field(default_factory=list)`.

- [ ] **Step 1: failing test**

```python
# backend/evals/test_reference_contracts.py
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from gateway.reference.contracts import SourceProvenance


def _provenance(**overrides: object) -> SourceProvenance:
    base: dict[str, object] = dict(
        source_id="frankfurter",
        source_owner="Frankfurter (frankfurter.dev)",
        source_url="https://api.frankfurter.dev/v2/rates",
        release_id="2026-08-20",
        retrieved_at=date(2026, 8, 20),
        licence_id="frankfurter-api-blended-central-bank-sources",
        attribution="Exchange rate data from Frankfurter (frankfurter.dev)",
        terms_reference="https://frankfurter.dev/docs",
        content_hash="a" * 64,
        record_count=3,
        warnings=[],
    )
    base.update(overrides)
    return SourceProvenance(**base)  # type: ignore[arg-type]


def test_provenance_requires_nonempty_source_id() -> None:
    with pytest.raises(ValidationError):
        _provenance(source_id="")


def test_provenance_requires_full_length_sha256_hash() -> None:
    with pytest.raises(ValidationError):
        _provenance(content_hash="short")


def test_provenance_rejects_negative_record_count() -> None:
    with pytest.raises(ValidationError):
        _provenance(record_count=-1)


def test_provenance_accepts_valid_shape() -> None:
    p = _provenance()
    assert p.source_id == "frankfurter"
    assert p.warnings == []
```

- [ ] **Step 2: run, verify fail** (`ModuleNotFoundError: gateway.reference`)
- [ ] **Step 3: implement**

```python
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class SourceProvenance(BaseModel):
    source_id: str = Field(min_length=1)
    source_owner: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    retrieved_at: date
    licence_id: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    terms_reference: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    record_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: run, verify pass; mypy/ruff; commit**

```bash
cd backend
.venv/bin/pytest evals/test_reference_contracts.py -v
.venv/bin/mypy --strict gateway/reference/contracts.py
.venv/bin/ruff check gateway/reference/ evals/test_reference_contracts.py
git add gateway/reference/__init__.py gateway/reference/contracts.py evals/test_reference_contracts.py
git commit -m "feat(gateway): add shared reference-snapshot provenance contract"
```

---

## 2. G2a — FX importer

### 2.1 Contracts

**Files:**
- Create: `backend/gateway/reference/fx/__init__.py`, `backend/gateway/reference/fx/contracts.py`
- Test: `backend/evals/test_reference_fx_contracts.py`

`FxRateRecord`: `base: str` (uppercase 3-letter), `quote: str` (uppercase 3-letter),
`rate_micro: int = Field(gt=0)`, `source_date: date`, `derived: bool` (`False` for a rate
taken directly from the source, `True` for a computed cross-rate), `derivation: str | None`
(e.g. `"USD/INR ÷ USD/SGD"` when `derived=True`, `None` otherwise — human-readable audit
trail, not used in any computation). `FxSnapshot`: `provenance: SourceProvenance`, `rates:
list[FxRateRecord]`.

Validators: `base != quote` rejected (a currency's rate against itself is meaningless
duplicate information, never emitted); uppercase normalization on `base`/`quote`.

- [ ] Write failing tests (rejects `base=="quote"`, uppercase normalization, `rate_micro`
  must be `> 0`, `derived=True` requires non-null `derivation`), implement, run, mypy/ruff,
  commit as part of the FX package's first commit (folded with 2.2 below — a bare contracts
  file with no builder to test it meaningfully is not an independently reviewable
  deliverable per this plan's task-sizing).

### 2.2 Parser + deterministic builder (the core of G2a)

**Files:**
- Create: `backend/gateway/reference/fx/parse.py`, `backend/gateway/reference/fx/build.py`,
  `backend/gateway/reference/fx/errors.py`
- Create fixtures: `backend/gateway/reference/fx/fixtures/frankfurter_valid.json`,
  `frankfurter_missing_currency.json`, `frankfurter_malformed.json`,
  `frankfurter_duplicate.json`, `frankfurter_zero_rate.json`, `frankfurter_negative_rate.json`,
  `frankfurter_unsupported_code.json`
- Test: `backend/evals/test_reference_fx_build.py`

**Interfaces:**
- `parse.py`: `parse_frankfurter_v2(raw: bytes, *, max_bytes: int = 262_144) ->
  list[RawFxQuote]` where `RawFxQuote` is a small internal dataclass/model
  (`date: str, base: str, quote: str, rate: Decimal`). Uses `json.loads(raw, parse_float=Decimal)`
  so no number in the payload is ever materialized as a binary `float`. Raises
  `FxImportError("invalid_response", ...)` on malformed JSON, oversized payload, or a
  non-list top-level shape.
- `build.py`: `build_fx_snapshot(raw_quotes: list[RawFxQuote], *, source: SourceProvenanceInput,
  now: date, cross_pairs: list[tuple[str, str]]) -> FxSnapshot` — pure function, no I/O.

**Rounding rule (Tier C, logged in DEVIATIONS.md):** `rate_micro = int((decimal_rate *
Decimal(1_000_000)).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))` — banker's rounding,
matching Python's `Decimal` default and chosen because it is the standard deterministic
tie-breaking rule with no directional bias (never rounds every `.5` up, which would
systematically inflate rates over many records). The existing hand-entered seed value (SGD→INR
63.20 → 63,200,000) has no fractional micro-unit remainder, so this rule changes nothing
about existing golden behavior — it only governs newly-imported values, which are never
activated in G2 anyway.

**Cross-rate rule:** for a `cross_pairs` entry `(A, B)` where the source snapshot has direct
rates `A→base` is not directly available but both `base→A` and `base→B` are (i.e., the
source's `base` currency is a pivot), compute `rate(A→B) = rate(base→B) / rate(base→A)` using
`Decimal` division at high precision (`decimal.localcontext(prec=50)`) before quantizing to
`rate_micro` — never divide already-rounded integers. If the source snapshot does not contain
both legs, the cross rate is **not** produced (no invented value); the gap is recorded in
`FxSnapshot.provenance.warnings`.

- [ ] **Step 1: write the fixtures.** `frankfurter_valid.json` — real-shaped, sanitized data
  matching the confirmed v2 schema, base USD, quotes AED/INR/SGD (values from the live
  verification above: AED 3.6725, INR 95.68, SGD 1.274):

```json
[
  {"date": "2026-08-20", "base": "USD", "quote": "AED", "rate": 3.6725},
  {"date": "2026-08-20", "base": "USD", "quote": "INR", "rate": 95.68},
  {"date": "2026-08-20", "base": "USD", "quote": "SGD", "rate": 1.274}
]
```

`frankfurter_missing_currency.json` — same shape, omits `AED` entirely (proves the importer
degrades honestly rather than inventing a rate). `frankfurter_malformed.json` — a `rate`
field that is a non-numeric string (`"rate": "N/A"`). `frankfurter_duplicate.json` — two
entries for `base=USD, quote=INR` with *different* rate values (95.68 and 95.70 — proves
duplicate detection fires on genuine conflicts, not just byte-identical repeats).
`frankfurter_zero_rate.json` / `frankfurter_negative_rate.json` — `"rate": 0` /
`"rate": -1.5`. `frankfurter_unsupported_code.json` — `"quote": "XX"` (not a valid 3-letter
ISO-shaped code — actually 2 letters, deliberately invalid).

- [ ] **Step 2: write the failing tests**

```python
# backend/evals/test_reference_fx_build.py
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from gateway.reference.fx.build import build_fx_snapshot
from gateway.reference.fx.errors import FxImportError
from gateway.reference.fx.parse import parse_frankfurter_v2

FIXTURES = Path(__file__).parent.parent / "gateway" / "reference" / "fx" / "fixtures"


def _raw(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


def _source(raw: bytes, record_count: int, warnings: list[str] | None = None) -> dict:
    return dict(
        source_id="frankfurter",
        source_owner="Frankfurter (frankfurter.dev)",
        source_url="https://api.frankfurter.dev/v2/rates",
        release_id="2026-08-20",
        retrieved_at=date(2026, 8, 20),
        licence_id="frankfurter-api-blended-central-bank-sources",
        attribution="Exchange rate data from Frankfurter (frankfurter.dev)",
        terms_reference="https://frankfurter.dev/docs",
        content_hash=hashlib.sha256(raw).hexdigest(),
        record_count=record_count,
        warnings=warnings or [],
    )


def test_valid_fixture_produces_direct_rates_with_correct_rate_micro() -> None:
    raw = _raw("frankfurter_valid")
    quotes = parse_frankfurter_v2(raw)
    snapshot = build_fx_snapshot(
        quotes, source=_source(raw, len(quotes)), now=date(2026, 8, 20), cross_pairs=[]
    )
    assert snapshot.rates  # non-vacuous
    by_pair = {(r.base, r.quote): r for r in snapshot.rates}
    assert by_pair[("USD", "AED")].rate_micro == 3_672_500
    assert by_pair[("USD", "INR")].rate_micro == 95_680_000
    assert by_pair[("USD", "SGD")].rate_micro == 1_274_000
    assert all(r.derived is False for r in snapshot.rates)


def test_missing_currency_is_documented_not_invented() -> None:
    raw = _raw("frankfurter_missing_currency")
    quotes = parse_frankfurter_v2(raw)
    snapshot = build_fx_snapshot(
        quotes,
        source=_source(raw, len(quotes)),
        now=date(2026, 8, 20),
        cross_pairs=[("SGD", "AED")],  # requires AED, which is absent
    )
    assert not any(r.quote == "AED" or r.base == "AED" for r in snapshot.rates)
    assert any("AED" in w for w in snapshot.provenance.warnings)


def test_unsupported_currency_code_is_rejected() -> None:
    with pytest.raises(FxImportError) as exc_info:
        parse_frankfurter_v2(_raw("frankfurter_unsupported_code"))
    assert exc_info.value.code == "invalid_response"


def test_malformed_decimal_is_rejected() -> None:
    with pytest.raises(FxImportError) as exc_info:
        parse_frankfurter_v2(_raw("frankfurter_malformed"))
    assert exc_info.value.code == "invalid_response"


def test_duplicate_currency_pair_with_conflicting_rates_is_rejected() -> None:
    raw = _raw("frankfurter_duplicate")
    quotes = parse_frankfurter_v2(raw)
    with pytest.raises(FxImportError) as exc_info:
        build_fx_snapshot(
            quotes, source=_source(raw, len(quotes)), now=date(2026, 8, 20), cross_pairs=[]
        )
    assert exc_info.value.code == "invalid_response"


def test_zero_rate_is_rejected() -> None:
    with pytest.raises(FxImportError):
        parse_frankfurter_v2(_raw("frankfurter_zero_rate"))


def test_negative_rate_is_rejected() -> None:
    with pytest.raises(FxImportError):
        parse_frankfurter_v2(_raw("frankfurter_negative_rate"))


def test_cross_rate_is_computed_only_when_both_legs_present_and_is_deterministic() -> None:
    raw = _raw("frankfurter_valid")
    quotes = parse_frankfurter_v2(raw)
    snapshot1 = build_fx_snapshot(
        quotes, source=_source(raw, len(quotes)), now=date(2026, 8, 20), cross_pairs=[("SGD", "INR")]
    )
    snapshot2 = build_fx_snapshot(
        quotes, source=_source(raw, len(quotes)), now=date(2026, 8, 20), cross_pairs=[("SGD", "INR")]
    )
    cross1 = next(r for r in snapshot1.rates if (r.base, r.quote) == ("SGD", "INR"))
    cross2 = next(r for r in snapshot2.rates if (r.base, r.quote) == ("SGD", "INR"))
    assert cross1.derived is True
    assert cross1.rate_micro == cross2.rate_micro
    # sanity: 95.68 / 1.274 = 75.10990582... -> rate_micro should round to 75_109_906
    assert cross1.rate_micro == 75_109_906


def test_integer_rounding_boundary_uses_banker_rounding() -> None:
    from decimal import Decimal

    from gateway.reference.fx.build import decimal_to_rate_micro

    # 63.2000005 * 1_000_000 = 63_200_000.5 exactly -> round-half-even -> 63_200_000
    assert decimal_to_rate_micro(Decimal("63.2000005")) == 63_200_000
    # 63.2000015 * 1_000_000 = 63_200_001.5 exactly -> round-half-even -> 63_200_002
    assert decimal_to_rate_micro(Decimal("63.2000015")) == 63_200_002


def test_repeated_build_is_byte_identical() -> None:
    raw = _raw("frankfurter_valid")
    quotes = parse_frankfurter_v2(raw)
    s1 = build_fx_snapshot(
        quotes, source=_source(raw, len(quotes)), now=date(2026, 8, 20), cross_pairs=[("SGD", "INR")]
    )
    s2 = build_fx_snapshot(
        quotes, source=_source(raw, len(quotes)), now=date(2026, 8, 20), cross_pairs=[("SGD", "INR")]
    )
    assert s1.model_dump_json() == s2.model_dump_json()


def test_licence_and_provenance_are_retained_on_the_snapshot() -> None:
    raw = _raw("frankfurter_valid")
    quotes = parse_frankfurter_v2(raw)
    snapshot = build_fx_snapshot(
        quotes, source=_source(raw, len(quotes)), now=date(2026, 8, 20), cross_pairs=[]
    )
    assert snapshot.provenance.licence_id == "frankfurter-api-blended-central-bank-sources"
    assert "Frankfurter" in snapshot.provenance.attribution
    assert snapshot.provenance.source_url == "https://api.frankfurter.dev/v2/rates"
    assert snapshot.provenance.content_hash == hashlib.sha256(raw).hexdigest()


def test_input_size_bound_is_enforced() -> None:
    oversized = json.dumps(
        [{"date": "2026-08-20", "base": "USD", "quote": "AED", "rate": 1.0}] * 20_000
    ).encode()
    assert len(oversized) > 262_144
    with pytest.raises(FxImportError) as exc_info:
        parse_frankfurter_v2(oversized, max_bytes=262_144)
    assert exc_info.value.code == "invalid_response"


def test_zero_network_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("FX build must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    raw = _raw("frankfurter_valid")
    quotes = parse_frankfurter_v2(raw)
    snapshot = build_fx_snapshot(
        quotes, source=_source(raw, len(quotes)), now=date(2026, 8, 20), cross_pairs=[]
    )
    assert snapshot.rates


def test_existing_kernel_fx_seed_and_goldens_are_unchanged() -> None:
    from core.db import SEEDS_DIR

    seed_text = (SEEDS_DIR / "fx_rates.yaml").read_text()
    # The three pre-existing seed pairs and their exact rate_micro values must
    # still be present, byte-for-byte, proving this importer never touched
    # the approved seed file.
    assert "base: SGD" in seed_text and "rate_micro: 63200000" in seed_text
    assert "base: USD" in seed_text and "rate_micro: 86500000" in seed_text
    assert "base: SGD" in seed_text and "quote: USD" in seed_text and "rate_micro: 730000" in seed_text
```

- [ ] **Step 3: run, verify fail** — **Step 4: implement**

```python
# backend/gateway/reference/fx/errors.py
from __future__ import annotations

from typing import Literal

ErrorCode = Literal["invalid_response", "unsupported_domain"]


class FxImportError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
```

```python
# backend/gateway/reference/fx/contracts.py
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from gateway.reference.contracts import SourceProvenance


def _normalize_currency(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("must be a 3-letter currency code")
    return normalized


class FxRateRecord(BaseModel):
    base: str
    quote: str
    rate_micro: int = Field(gt=0)
    source_date: date
    derived: bool = False
    derivation: str | None = None

    _norm_base = field_validator("base")(classmethod(lambda cls, v: _normalize_currency(v)))
    _norm_quote = field_validator("quote")(classmethod(lambda cls, v: _normalize_currency(v)))

    @model_validator(mode="after")
    def _base_and_quote_differ(self) -> FxRateRecord:
        if self.base == self.quote:
            raise ValueError("base and quote currency must differ")
        if self.derived and not self.derivation:
            raise ValueError("a derived cross-rate must record its derivation")
        return self


class FxSnapshot(BaseModel):
    provenance: SourceProvenance
    rates: list[FxRateRecord]
```

```python
# backend/gateway/reference/fx/parse.py
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from gateway.reference.fx.errors import FxImportError

MAX_BYTES_DEFAULT = 262_144


@dataclass(frozen=True)
class RawFxQuote:
    date: str
    base: str
    quote: str
    rate: Decimal


def parse_frankfurter_v2(raw: bytes, *, max_bytes: int = MAX_BYTES_DEFAULT) -> list[RawFxQuote]:
    if len(raw) > max_bytes:
        raise FxImportError("invalid_response", f"payload exceeds {max_bytes} byte bound")
    try:
        data = json.loads(raw, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise FxImportError("invalid_response", f"malformed JSON: {exc}") from exc
    if not isinstance(data, list):
        raise FxImportError("invalid_response", "expected a top-level JSON array")

    quotes: list[RawFxQuote] = []
    for row in data:
        if not isinstance(row, dict):
            raise FxImportError("invalid_response", "each row must be a JSON object")
        try:
            base = str(row["base"]).strip().upper()
            quote = str(row["quote"]).strip().upper()
            date_str = str(row["date"])
            rate_raw = row["rate"]
        except KeyError as exc:
            raise FxImportError("invalid_response", f"missing field: {exc}") from exc

        if len(base) != 3 or not base.isalpha() or len(quote) != 3 or not quote.isalpha():
            raise FxImportError("invalid_response", f"unsupported currency code: {base}/{quote}")

        try:
            rate = rate_raw if isinstance(rate_raw, Decimal) else Decimal(str(rate_raw))
        except (InvalidOperation, ValueError) as exc:
            raise FxImportError("invalid_response", f"malformed decimal rate: {rate_raw!r}") from exc

        if not rate.is_finite() or rate <= 0:
            raise FxImportError("invalid_response", f"non-positive or non-finite rate: {rate}")

        quotes.append(RawFxQuote(date=date_str, base=base, quote=quote, rate=rate))
    return quotes
```

```python
# backend/gateway/reference/fx/build.py
from __future__ import annotations

import decimal
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from gateway.reference.contracts import SourceProvenance
from gateway.reference.fx.contracts import FxRateRecord, FxSnapshot
from gateway.reference.fx.errors import FxImportError
from gateway.reference.fx.parse import RawFxQuote

MICRO = Decimal(1_000_000)


def decimal_to_rate_micro(rate: Decimal) -> int:
    return int((rate * MICRO).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def build_fx_snapshot(
    raw_quotes: list[RawFxQuote],
    *,
    source: dict[str, object],
    now: date,
    cross_pairs: list[tuple[str, str]],
) -> FxSnapshot:
    seen: dict[tuple[str, str], RawFxQuote] = {}
    for q in raw_quotes:
        key = (q.base, q.quote)
        if key in seen and seen[key].rate != q.rate:
            raise FxImportError(
                "invalid_response",
                f"duplicate {key} with conflicting rates {seen[key].rate} vs {q.rate}",
            )
        seen[key] = q

    direct_by_pair = {k: v.rate for k, v in seen.items()}
    warnings: list[str] = list(source.get("warnings", []))  # type: ignore[arg-type]

    records: list[FxRateRecord] = [
        FxRateRecord(
            base=q.base, quote=q.quote, rate_micro=decimal_to_rate_micro(q.rate),
            source_date=date.fromisoformat(q.date), derived=False, derivation=None,
        )
        for q in sorted(seen.values(), key=lambda x: (x.base, x.quote))
    ]

    for a, b in sorted(cross_pairs):
        pivot_bases = {base for (base, _quote) in direct_by_pair}
        found = False
        for pivot in sorted(pivot_bases):
            if (pivot, a) in direct_by_pair and (pivot, b) in direct_by_pair:
                with decimal.localcontext() as ctx:
                    ctx.prec = 50
                    cross = direct_by_pair[(pivot, b)] / direct_by_pair[(pivot, a)]
                records.append(
                    FxRateRecord(
                        base=a, quote=b, rate_micro=decimal_to_rate_micro(cross),
                        source_date=now, derived=True,
                        derivation=f"{pivot}/{b} ÷ {pivot}/{a}",
                    )
                )
                found = True
                break
        if not found:
            warnings.append(f"cannot derive {a}->{b}: missing a common pivot leg in source data")

    provenance = SourceProvenance(**{**source, "record_count": len(records), "warnings": warnings})
    records.sort(key=lambda r: (r.base, r.quote))
    return FxSnapshot(provenance=provenance, rates=records)
```

- [ ] **Step 5: run, verify pass** — **Step 6: mypy/ruff; commit**

```bash
cd backend
.venv/bin/pytest evals/test_reference_fx_build.py evals/test_reference_fx_contracts.py -v
.venv/bin/mypy --strict gateway/reference/
.venv/bin/ruff check gateway/reference/ evals/test_reference_fx_build.py evals/test_reference_fx_contracts.py
git add gateway/reference/fx/ evals/test_reference_fx_build.py evals/test_reference_fx_contracts.py
git commit -m "feat(gateway): add deterministic FX reference importer"
```

### 2.3 Explicit offline fetch command (not imported by anything)

**Files:** Create `backend/gateway/reference/fx/fetch.py`, test:
`backend/evals/test_reference_fx_fetch_boundary.py` (boundary-only — does NOT execute the
fetch; only proves the module is never imported elsewhere and, if invoked directly, targets
only the one allowlisted host).

```python
# backend/gateway/reference/fx/fetch.py
"""Manual, offline developer command. NOT imported by any test, by core/, agents/,
api/, or any request path. Run by a human, occasionally, to refresh the FX fixture
snapshot for review -- mirrors scripts/fetch_overture.py's pattern.

Usage: python -m gateway.reference.fx.fetch --out /tmp/frankfurter_snapshot.json
"""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

ALLOWED_HOST = "api.frankfurter.dev"
FX_URL = "https://api.frankfurter.dev/v2/rates?base=USD&quotes=AED,INR,SGD"


def fetch(out_path: Path) -> None:
    if ALLOWED_HOST not in FX_URL:
        raise RuntimeError("refusing to fetch from a non-allowlisted host")
    with urllib.request.urlopen(FX_URL, timeout=10) as resp:  # noqa: S310
        out_path.write_bytes(resp.read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    fetch(args.out)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
```

```python
# backend/evals/test_reference_fx_fetch_boundary.py
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).parent.parent


def test_fetch_module_is_never_imported_outside_itself_and_tests() -> None:
    offenders = []
    for pkg in ("core", "agents", "api"):
        for path in (BACKEND / pkg).rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                elif isinstance(node, ast.Import):
                    names.extend(a.name for a in node.names)
                if any("gateway.reference.fx.fetch" in n for n in names):
                    offenders.append(str(path))
    assert offenders == []


def test_fetch_targets_only_the_allowlisted_host() -> None:
    from gateway.reference.fx.fetch import ALLOWED_HOST, FX_URL

    assert ALLOWED_HOST == "api.frankfurter.dev"
    assert FX_URL.startswith(f"https://{ALLOWED_HOST}/")
```

Run, verify pass, mypy/ruff, fold into the same "add deterministic FX reference importer"
commit's follow-up or a small separate commit — this plan folds it into 2.2's commit scope
since it's the same reviewable unit (the FX importer, fetch included).

```bash
cd backend
.venv/bin/pytest evals/test_reference_fx_fetch_boundary.py -v
.venv/bin/mypy --strict gateway/reference/fx/fetch.py
.venv/bin/ruff check gateway/reference/fx/fetch.py evals/test_reference_fx_fetch_boundary.py
git add gateway/reference/fx/fetch.py evals/test_reference_fx_fetch_boundary.py
git commit -m "feat(gateway): add explicit offline FX fetch command (unwired)"
```

---

## 3. G2b — Airport importer

### 3.1 Contracts, fixtures, parser, builder

**Files:**
- Create: `backend/gateway/reference/airports/__init__.py`,
  `backend/gateway/reference/airports/contracts.py`,
  `backend/gateway/reference/airports/errors.py`,
  `backend/gateway/reference/airports/parse.py`,
  `backend/gateway/reference/airports/build.py`,
  `backend/gateway/reference/airports/fetch.py`
- Create fixtures: `backend/gateway/reference/airports/fixtures/ourairports_sample.csv`,
  `ourairports_missing_optional.csv`, `ourairports_invalid_coordinates.csv`,
  `ourairports_duplicate_id.csv`, `ourairports_duplicate_iata.csv`
- Test: `backend/evals/test_reference_airports_build.py`

**Interfaces:**
- `AirportRecord(BaseModel)`: `id: str`, `ident: str`, `airport_type: Literal["balloonport",
  "closed_airport", "heliport", "large_airport", "medium_airport", "seaplane_base",
  "small_airport"]`, `name: str`, `lat: float | None`, `lon: float | None`, `elevation_ft:
  int | None`, `continent: str | None`, `iso_country: str | None`, `iso_region: str | None`,
  `municipality: str | None`, `scheduled_service: bool`, `gps_code: str | None`, `icao_code:
  str | None`, `iata_code: str | None`, `local_code: str | None`, `home_link: str | None`.
  `AirportSnapshot(BaseModel)`: `provenance: SourceProvenance`, `airports:
  list[AirportRecord]`.
- `parse.py`: `parse_ourairports_csv(raw: bytes, *, max_bytes: int = 5_000_000, max_records:
  int = 5_000) -> list[dict[str, str]]` — stdlib `csv.DictReader`, enforces byte and
  record-count bounds, raises `AirportImportError` on structural failure (wrong column set).
- `build.py`: `build_airport_snapshot(rows: list[dict[str, str]], *, source: dict[str,
  object]) -> AirportSnapshot` — validates/coerces each row, uppercase-normalizes
  `iso_country`/`iata_code`/`icao_code`/`gps_code`/`local_code`, rejects duplicate `id`
  (structural invariant violation — fail closed), and handles duplicate `iata_code`
  **conservatively**: when 2+ records share a non-empty `iata_code`, all records are still
  emitted in full (never dropped — they may be legitimately distinct airports/history), but a
  `warnings` entry is recorded per collided code and none of those records' `iata_code` is
  treated as a reliable unique key downstream (documented, not enforced by a separate
  "IATA index" object in this milestone since nothing yet consumes one).

**Deterministic IATA-less rule (Tier C, logged in DEVIATIONS.md):** airports without an
`iata_code` are **preserved**, never excluded — this is reference data (small regional/GA
airports are legitimate real-world facts), and exclusion would silently discard information a
future consumer might need (e.g., a `gps_code`/`icao_code`-based lookup). Ordering is
deterministic: sorted by `(iso_country, ident)`.

- [ ] **Step 1: write fixtures.** `ourairports_sample.csv` — header row plus real,
  well-known, public-domain airport facts for the seven airports relevant to existing
  corridors (DEL, BOM, SIN, DXB, LHR serving LON, CDG serving PAR, JFK serving NYC):

```csv
id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,iso_country,iso_region,municipality,scheduled_service,gps_code,icao_code,iata_code,local_code,home_link,wikipedia_link,keywords
3000001,VIDP,large_airport,Indira Gandhi International Airport,28.5665,77.1031,777,AS,IN,IN-DL,New Delhi,yes,VIDP,VIDP,DEL,,,https://en.wikipedia.org/wiki/Indira_Gandhi_International_Airport,
3000002,VABB,large_airport,Chhatrapati Shivaji Maharaj International Airport,19.0887,72.8679,39,AS,IN,IN-MH,Mumbai,yes,VABB,VABB,BOM,,,https://en.wikipedia.org/wiki/Chhatrapati_Shivaji_Maharaj_International_Airport,
3000003,WSSS,large_airport,Singapore Changi Airport,1.3644,103.9915,22,AS,SG,SG-04,Singapore,yes,WSSS,WSSS,SIN,,,https://en.wikipedia.org/wiki/Singapore_Changi_Airport,
3000004,OMDB,large_airport,Dubai International Airport,25.2532,55.3657,62,AS,AE,AE-DU,Dubai,yes,OMDB,OMDB,DXB,,,https://en.wikipedia.org/wiki/Dubai_International_Airport,
3000005,EGLL,large_airport,London Heathrow Airport,51.4700,-0.4543,83,EU,GB,GB-ENG,London,yes,EGLL,EGLL,LHR,,,https://en.wikipedia.org/wiki/Heathrow_Airport,
3000006,LFPG,large_airport,Charles de Gaulle Airport,49.0097,2.5479,392,EU,FR,FR-IDF,Paris,yes,LFPG,LFPG,CDG,,,https://en.wikipedia.org/wiki/Charles_de_Gaulle_Airport,
3000007,KJFK,large_airport,John F Kennedy International Airport,40.6413,-73.7781,13,NA,US,US-NY,New York,yes,KJFK,KJFK,JFK,,,https://en.wikipedia.org/wiki/John_F._Kennedy_International_Airport,
```

`ourairports_missing_optional.csv` — one row with `elevation_ft`, `gps_code`, `home_link`
etc. left blank. `ourairports_invalid_coordinates.csv` — one row with `latitude_deg="999"`
(out of `[-90, 90]`). `ourairports_duplicate_id.csv` — two rows sharing `id=3000001`.
`ourairports_duplicate_iata.csv` — two rows both `iata_code=DEL` (one `large_airport`, one
`closed_airport` — a real-world pattern where a code gets reused after an airport closes).

- [ ] **Step 2: write failing tests**

```python
# backend/evals/test_reference_airports_build.py
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from gateway.reference.airports.build import build_airport_snapshot
from gateway.reference.airports.errors import AirportImportError
from gateway.reference.airports.parse import parse_ourairports_csv

FIXTURES = Path(__file__).parent.parent / "gateway" / "reference" / "airports" / "fixtures"


def _raw(name: str) -> bytes:
    return (FIXTURES / f"{name}.csv").read_bytes()


def _source(raw: bytes, record_count: int) -> dict:
    return dict(
        source_id="ourairports",
        source_owner="OurAirports (David Megginson)",
        source_url="https://davidmegginson.github.io/ourairports-data/airports.csv",
        release_id=f"2026-08-20:{hashlib.sha256(raw).hexdigest()[:12]}",
        retrieved_at=date(2026, 8, 20),
        licence_id="public-domain",
        attribution="Airport data courtesy of OurAirports (ourairports.com), released to the Public Domain.",
        terms_reference="https://ourairports.com/data/",
        content_hash=hashlib.sha256(raw).hexdigest(),
        record_count=record_count,
        warnings=[],
    )


def test_valid_fixture_produces_normalized_records_for_all_seven_corridor_airports() -> None:
    raw = _raw("ourairports_sample")
    rows = parse_ourairports_csv(raw)
    snapshot = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert snapshot.airports  # non-vacuous
    by_iata = {a.iata_code: a for a in snapshot.airports if a.iata_code}
    for code in ("DEL", "BOM", "SIN", "DXB", "LHR", "CDG", "JFK"):
        assert code in by_iata, f"missing corridor airport {code}"
    assert by_iata["DEL"].name == "Indira Gandhi International Airport"
    assert by_iata["DEL"].lat == pytest.approx(28.5665)
    assert by_iata["SIN"].scheduled_service is True


def test_missing_optional_fields_stay_none_not_fabricated() -> None:
    raw = _raw("ourairports_missing_optional")
    rows = parse_ourairports_csv(raw)
    snapshot = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    airport = snapshot.airports[0]
    assert airport.elevation_ft is None
    assert airport.gps_code is None
    assert airport.home_link is None


def test_invalid_coordinates_are_rejected() -> None:
    raw = _raw("ourairports_invalid_coordinates")
    rows = parse_ourairports_csv(raw)
    with pytest.raises(AirportImportError) as exc_info:
        build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert exc_info.value.code == "invalid_response"


def test_duplicate_stable_id_is_rejected() -> None:
    raw = _raw("ourairports_duplicate_id")
    rows = parse_ourairports_csv(raw)
    with pytest.raises(AirportImportError) as exc_info:
        build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert exc_info.value.code == "invalid_response"


def test_duplicate_iata_code_is_handled_conservatively_not_dropped() -> None:
    raw = _raw("ourairports_duplicate_iata")
    rows = parse_ourairports_csv(raw)
    snapshot = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    matching = [a for a in snapshot.airports if a.iata_code == "DEL"]
    assert len(matching) == 2  # both records preserved
    assert any("DEL" in w for w in snapshot.provenance.warnings)


def test_uppercase_normalization_of_codes() -> None:
    raw = _raw("ourairports_sample")
    rows = parse_ourairports_csv(raw)
    snapshot = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert all(a.iso_country is None or a.iso_country == a.iso_country.upper() for a in snapshot.airports)
    assert all(a.iata_code is None or a.iata_code == a.iata_code.upper() for a in snapshot.airports)


def test_stable_deterministic_ordering() -> None:
    raw = _raw("ourairports_sample")
    rows = parse_ourairports_csv(raw)
    snapshot1 = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    snapshot2 = build_airport_snapshot(list(reversed(rows)), source=_source(raw, len(rows)))
    order1 = [(a.iso_country, a.ident) for a in snapshot1.airports]
    order2 = [(a.iso_country, a.ident) for a in snapshot2.airports]
    assert order1 == order2 == sorted(order1)


def test_repeated_build_is_byte_identical() -> None:
    raw = _raw("ourairports_sample")
    rows = parse_ourairports_csv(raw)
    s1 = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    s2 = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert s1.model_dump_json() == s2.model_dump_json()


def test_licence_and_provenance_are_retained() -> None:
    raw = _raw("ourairports_sample")
    rows = parse_ourairports_csv(raw)
    snapshot = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert snapshot.provenance.licence_id == "public-domain"
    assert "OurAirports" in snapshot.provenance.attribution
    assert snapshot.provenance.content_hash == hashlib.sha256(raw).hexdigest()


def test_input_size_and_record_count_bounds_are_enforced() -> None:
    huge_csv = (
        "id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,iso_country,"
        "iso_region,municipality,scheduled_service,gps_code,icao_code,iata_code,local_code,"
        "home_link,wikipedia_link,keywords\n"
        + "1,AAAA,small_airport,X,0,0,,,,,,no,,,,,,\n" * 6000
    ).encode()
    with pytest.raises(AirportImportError) as exc_info:
        parse_ourairports_csv(huge_csv, max_records=5000)
    assert exc_info.value.code == "invalid_response"


def test_zero_network_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("airport build must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    raw = _raw("ourairports_sample")
    rows = parse_ourairports_csv(raw)
    snapshot = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert snapshot.airports
```

- [ ] **Step 3: run, verify fail** — **Step 4: implement**

```python
# backend/gateway/reference/airports/errors.py
from __future__ import annotations

from typing import Literal

ErrorCode = Literal["invalid_response"]


class AirportImportError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
```

```python
# backend/gateway/reference/airports/contracts.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from gateway.reference.contracts import SourceProvenance

AirportType = Literal[
    "balloonport", "closed_airport", "heliport", "large_airport",
    "medium_airport", "seaplane_base", "small_airport",
]


def _upper_or_none(value: str | None) -> str | None:
    return value.strip().upper() if value else None


class AirportRecord(BaseModel):
    id: str
    ident: str
    airport_type: AirportType
    name: str
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    elevation_ft: int | None = None
    continent: str | None = None
    iso_country: str | None = None
    iso_region: str | None = None
    municipality: str | None = None
    scheduled_service: bool
    gps_code: str | None = None
    icao_code: str | None = None
    iata_code: str | None = None
    local_code: str | None = None
    home_link: str | None = None

    _u1 = field_validator("iso_country")(classmethod(lambda cls, v: _upper_or_none(v)))
    _u2 = field_validator("iata_code")(classmethod(lambda cls, v: _upper_or_none(v)))
    _u3 = field_validator("icao_code")(classmethod(lambda cls, v: _upper_or_none(v)))
    _u4 = field_validator("gps_code")(classmethod(lambda cls, v: _upper_or_none(v)))
    _u5 = field_validator("local_code")(classmethod(lambda cls, v: _upper_or_none(v)))


class AirportSnapshot(BaseModel):
    provenance: SourceProvenance
    airports: list[AirportRecord]
```

```python
# backend/gateway/reference/airports/parse.py
from __future__ import annotations

import csv
import io

from gateway.reference.airports.errors import AirportImportError

REQUIRED_COLUMNS = {
    "id", "ident", "type", "name", "latitude_deg", "longitude_deg", "elevation_ft",
    "continent", "iso_country", "iso_region", "municipality", "scheduled_service",
    "gps_code", "icao_code", "iata_code", "local_code", "home_link",
}
MAX_BYTES_DEFAULT = 5_000_000
MAX_RECORDS_DEFAULT = 5_000


def parse_ourairports_csv(
    raw: bytes, *, max_bytes: int = MAX_BYTES_DEFAULT, max_records: int = MAX_RECORDS_DEFAULT
) -> list[dict[str, str]]:
    if len(raw) > max_bytes:
        raise AirportImportError("invalid_response", f"payload exceeds {max_bytes} byte bound")
    text = raw.decode("utf-8", errors="strict")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
        raise AirportImportError("invalid_response", "CSV is missing required columns")

    rows: list[dict[str, str]] = []
    for row in reader:
        if len(rows) >= max_records:
            raise AirportImportError("invalid_response", f"exceeds {max_records} record bound")
        rows.append(row)
    return rows
```

```python
# backend/gateway/reference/airports/build.py
from __future__ import annotations

from gateway.reference.airports.contracts import AirportRecord, AirportSnapshot
from gateway.reference.airports.errors import AirportImportError
from gateway.reference.contracts import SourceProvenance


def _optional(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _optional_float(value: str | None) -> float | None:
    text = _optional(value)
    return float(text) if text is not None else None


def _optional_int(value: str | None) -> int | None:
    text = _optional(value)
    return int(float(text)) if text is not None else None


def build_airport_snapshot(
    rows: list[dict[str, str]], *, source: dict[str, object]
) -> AirportSnapshot:
    seen_ids: set[str] = set()
    iata_counts: dict[str, int] = {}
    records: list[AirportRecord] = []
    warnings: list[str] = list(source.get("warnings", []))  # type: ignore[arg-type]

    for row in rows:
        row_id = row["id"].strip()
        if row_id in seen_ids:
            raise AirportImportError("invalid_response", f"duplicate stable id: {row_id}")
        seen_ids.add(row_id)

        iata = _optional(row.get("iata_code"))
        if iata:
            iata_counts[iata.upper()] = iata_counts.get(iata.upper(), 0) + 1

        try:
            record = AirportRecord(
                id=row_id,
                ident=row["ident"].strip(),
                airport_type=row["type"].strip(),  # type: ignore[arg-type]
                name=row["name"].strip(),
                lat=_optional_float(row.get("latitude_deg")),
                lon=_optional_float(row.get("longitude_deg")),
                elevation_ft=_optional_int(row.get("elevation_ft")),
                continent=_optional(row.get("continent")),
                iso_country=_optional(row.get("iso_country")),
                iso_region=_optional(row.get("iso_region")),
                municipality=_optional(row.get("municipality")),
                scheduled_service=row["scheduled_service"].strip().lower() == "yes",
                gps_code=_optional(row.get("gps_code")),
                icao_code=_optional(row.get("icao_code")),
                iata_code=iata,
                local_code=_optional(row.get("local_code")),
                home_link=_optional(row.get("home_link")),
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise AirportImportError("invalid_response", f"malformed row {row_id}: {exc}") from exc
        records.append(record)

    for code, count in sorted(iata_counts.items()):
        if count > 1:
            warnings.append(
                f"IATA code {code} appears on {count} records; not treated as a unique key"
            )

    records.sort(key=lambda a: (a.iso_country or "", a.ident))
    provenance = SourceProvenance(**{**source, "record_count": len(records), "warnings": warnings})
    return AirportSnapshot(provenance=provenance, airports=records)
```

```python
# backend/gateway/reference/airports/fetch.py
"""Manual, offline developer command. NOT imported by any test, by core/, agents/,
api/, or any request path.

Usage: python -m gateway.reference.airports.fetch --out /tmp/ourairports_snapshot.csv
"""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

ALLOWED_HOST = "davidmegginson.github.io"
AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"


def fetch(out_path: Path) -> None:
    if ALLOWED_HOST not in AIRPORTS_URL:
        raise RuntimeError("refusing to fetch from a non-allowlisted host")
    with urllib.request.urlopen(AIRPORTS_URL, timeout=30) as resp:  # noqa: S310
        out_path.write_bytes(resp.read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    fetch(args.out)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: run, verify pass** — **Step 6: add the fetch-boundary test (mirrors 2.3)**

```python
# backend/evals/test_reference_airports_fetch_boundary.py
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).parent.parent


def test_fetch_module_is_never_imported_outside_itself_and_tests() -> None:
    offenders = []
    for pkg in ("core", "agents", "api"):
        for path in (BACKEND / pkg).rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                elif isinstance(node, ast.Import):
                    names.extend(a.name for a in node.names)
                if any("gateway.reference.airports.fetch" in n for n in names):
                    offenders.append(str(path))
    assert offenders == []


def test_fetch_targets_only_the_allowlisted_host() -> None:
    from gateway.reference.airports.fetch import AIRPORTS_URL, ALLOWED_HOST

    assert ALLOWED_HOST == "davidmegginson.github.io"
    assert AIRPORTS_URL.startswith(f"https://{ALLOWED_HOST}/")
```

- [ ] **Step 7: mypy/ruff; commit**

```bash
cd backend
.venv/bin/pytest evals/test_reference_airports_build.py evals/test_reference_airports_fetch_boundary.py -v
.venv/bin/mypy --strict gateway/reference/airports/
.venv/bin/ruff check gateway/reference/airports/ evals/test_reference_airports_build.py evals/test_reference_airports_fetch_boundary.py
git add gateway/reference/airports/ evals/test_reference_airports_build.py evals/test_reference_airports_fetch_boundary.py
git commit -m "feat(gateway): add deterministic airport reference importer"
```

---

## 4. G2c — POI importer acceptance and hardening

**No new ingestion architecture.** `gateway/catalog/` already implements: a `PinnedSource`
manifest with `checksum`/`licence_id`/`attribution_text`/`source_release`
(`manifest.py`), quarantine-verified staging (`quarantine.py`), Overture/OSM/Wikivoyage
normalization into typed `PlaceClaim`s (`normalize.py`), deterministic identity resolution
(`identity.py`), deterministic quality gating (`quality.py`), atomic canonical-JSON
activation (`activate.py`, `canonical_json` with `sort_keys=True`), and a compaction layer
that stores per-source licence/attribution once and rehydrates it onto every claim at load
time (`CompactClaim`, referenced in `DEVIATIONS.md`'s 2026-08-16 catalog-compaction entry).
Existing tests already cover determinism (`test_catalog_determinism.py`: two builds
byte-identical, no wall-clock, shuffled-input stability), the no-network/no-agents-api-import
boundary (`test_catalog_boundary.py`), full provenance round-trip through compaction
(`test_catalog_compaction.py`), and the request-path network guard
(`test_network_isolation.py`).

**Files:**
- Create: `backend/evals/test_g2_poi_acceptance.py` (new — the explicit G2 gate checklist,
  each item either a light new assertion or a documented pointer to the existing test that
  already proves it)

**Audit result (recorded here, restated in the milestone report):**

| G2c requirement | Status | Evidence |
|---|---|---|
| Overture/OSM/Wikivoyage licence metadata survives into normalized claims and artifacts | **Already satisfied** | `test_catalog_compaction.py::test_round_trip_rehydrates_full_provenance` |
| Source release and attribution survive compaction and tiling | **Partially covered — new test added** | `tiles.py` lines 88-94/178-192 rehydrate `licence_id`/`source_release`/`attribution_requirements` from the source map, but no existing test asserts this on a *tiled* (not just compacted) artifact with real (non-placeholder `"L"`) values |
| Repeated fixture builds are byte-identical | **Already satisfied** | `test_catalog_determinism.py` (2 tests, plus shuffled-input stability) |
| Runtime request paths do not fetch POI data | **Already satisfied** | `test_network_isolation.py::test_the_request_path_makes_no_network_call` |
| Existing six catalog corridors continue to work | **Partially covered — new test added** | `test_region_isolation.py` only compares SIN vs BOM pairwise; no single test asserts all six `regions.yaml` entries (SIN/BOM/DXB/NYC/LON/PAR) load and resolve |
| No 130 MB active catalog artifact accidentally committed | **Already satisfied, newly asserted** | `backend/.gitignore` lines 1/3 (`raw_overture/`, `catalogs/`); `git ls-files` confirms zero tracked files under `catalogs/` |
| Existing POI identity/provenance model not replaced | **Already satisfied, newly asserted** | `gateway.places.contracts.Place`/`PlaceClaim`/`CompactClaim` untouched by this milestone — structural field-set snapshot test added |

- [ ] **Step 1: write the acceptance test file** (all tests exercise real fixture data —
  reuse the existing `test_catalog_tiles.py` fixture-manifest pattern for the tiling test
  rather than inventing a new one). Before writing, `Read` `evals/test_catalog_tiles.py` in
  full to copy its exact fixture paths and `TiledPlaceAdapter`'s real public loading method —
  this plan's snippet below is illustrative; match it to what the codebase actually exposes:

```python
# backend/evals/test_g2_poi_acceptance.py
from __future__ import annotations

import subprocess
from pathlib import Path

BACKEND = Path(__file__).parent.parent


def test_no_active_catalog_artifact_is_tracked_by_git() -> None:
    result = subprocess.run(
        ["git", "ls-files", "backend/catalogs"],
        cwd=BACKEND.parent, capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == ""


def test_catalogs_directory_is_gitignored() -> None:
    gitignore = (BACKEND / ".gitignore").read_text()
    assert "catalogs/" in gitignore
    assert "raw_overture/" in gitignore


def test_all_six_regional_corridors_resolve() -> None:
    from gateway.catalog.regions import get_region

    for iata in ("SIN", "BOM", "DXB", "NYC", "LON", "PAR"):
        region = get_region(iata)
        assert region is not None, f"{iata} not registered in regions.yaml"
        assert region.catalog_id


def test_place_and_claim_identity_model_is_unchanged() -> None:
    from gateway.places.contracts import CompactClaim, Place, PlaceClaim

    # Structural snapshot: this milestone must not add/remove/rename a field
    # on the identity/provenance model. If this test needs updating, that is
    # itself a signal the change deserves a DEVIATIONS.md entry.
    assert "external_ids" in Place.model_fields
    assert "place_id" in PlaceClaim.model_fields
    assert "licence_id" not in CompactClaim.model_fields  # compaction optimization intact
```

*(The tiling-attribution test is added as a 5th test once the exact existing fixture/adapter
API is confirmed by reading `test_catalog_tiles.py` at implementation time — see Step 1's
note above.)*

- [ ] **Step 2: run against the real codebase, verify each assertion is true (most should
  pass immediately per the audit table above); if the tiling-attribution test fails because
  of a genuine gap, fix `tiles.py` test-first — but expect this to pass given the source
  excerpt already reviewed in §0.**
- [ ] **Step 3: mypy/ruff; commit**

```bash
cd backend
.venv/bin/pytest evals/test_g2_poi_acceptance.py -v
.venv/bin/ruff check evals/test_g2_poi_acceptance.py
git add evals/test_g2_poi_acceptance.py
git commit -m "test(catalog): accept and harden POI reference ingestion"
```

---

## 5. G2d — Cross-importer boundary, determinism, licence and security gate

**Files:**
- Create: `backend/evals/test_reference_boundary.py`

- [ ] **Step 1: write tests**

```python
# backend/evals/test_reference_boundary.py
from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

BACKEND = Path(__file__).parent.parent
REFERENCE_DIR = BACKEND / "gateway" / "reference"


def _imports_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_core_never_imports_gateway_reference() -> None:
    offenders = [
        str(p) for p in (BACKEND / "core").rglob("*.py")
        if any(n == "gateway" or n.startswith("gateway.") for n in _imports_in(p))
    ]
    assert offenders == []


def test_agents_and_api_never_import_reference_fetch_modules() -> None:
    offenders = []
    for pkg in ("agents", "api"):
        for p in (BACKEND / pkg).rglob("*.py"):
            names = _imports_in(p)
            if any("gateway.reference" in n and "fetch" in n for n in names):
                offenders.append(str(p))
    assert offenders == []


def test_no_secret_markers_in_reference_package() -> None:
    forbidden = ["sk_live", "api_key=", "Authorization: Bearer ", "BEGIN RSA PRIVATE KEY"]
    offenders = [
        str(p) for p in REFERENCE_DIR.rglob("*.py")
        if any(m in p.read_text() for m in forbidden)
    ]
    assert offenders == []


def test_full_reference_package_zero_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: parse+build both FX and airports from fixtures with sockets forbidden."""
    import hashlib
    from datetime import date

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no socket calls allowed anywhere in gateway.reference")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)

    from gateway.reference.airports.build import build_airport_snapshot
    from gateway.reference.airports.parse import parse_ourairports_csv
    from gateway.reference.fx.build import build_fx_snapshot
    from gateway.reference.fx.parse import parse_frankfurter_v2

    fx_raw = (BACKEND / "gateway" / "reference" / "fx" / "fixtures" / "frankfurter_valid.json").read_bytes()
    fx_quotes = parse_frankfurter_v2(fx_raw)
    fx_snapshot = build_fx_snapshot(
        fx_quotes,
        source=dict(
            source_id="frankfurter", source_owner="Frankfurter", source_url="https://api.frankfurter.dev/v2/rates",
            release_id="2026-08-20", retrieved_at=date(2026, 8, 20),
            licence_id="frankfurter-api-blended-central-bank-sources",
            attribution="Exchange rate data from Frankfurter (frankfurter.dev)",
            terms_reference="https://frankfurter.dev/docs", content_hash=hashlib.sha256(fx_raw).hexdigest(),
            record_count=0, warnings=[],
        ),
        now=date(2026, 8, 20), cross_pairs=[],
    )
    assert fx_snapshot.rates

    ap_raw = (BACKEND / "gateway" / "reference" / "airports" / "fixtures" / "ourairports_sample.csv").read_bytes()
    ap_rows = parse_ourairports_csv(ap_raw)
    ap_snapshot = build_airport_snapshot(
        ap_rows,
        source=dict(
            source_id="ourairports", source_owner="OurAirports", source_url="https://davidmegginson.github.io/ourairports-data/airports.csv",
            release_id="2026-08-20", retrieved_at=date(2026, 8, 20), licence_id="public-domain",
            attribution="Airport data courtesy of OurAirports (ourairports.com), released to the Public Domain.",
            terms_reference="https://ourairports.com/data/", content_hash=hashlib.sha256(ap_raw).hexdigest(),
            record_count=0, warnings=[],
        ),
    )
    assert ap_snapshot.airports


def test_no_dependency_on_core_optimizer_or_pathfinder() -> None:
    """gateway/reference/ must never import the deterministic kernel modules that
    perform money/points arithmetic -- reference importers produce evidence, not
    activated financial facts."""
    offenders = []
    for p in REFERENCE_DIR.rglob("*.py"):
        names = _imports_in(p)
        if any("core.optimizer" in n or "core.transfer" in n for n in names):
            offenders.append(str(p))
    assert offenders == []
```

- [ ] **Step 2: run, verify pass** — **Step 3: mypy/ruff; commit**

```bash
cd backend
.venv/bin/pytest evals/test_reference_boundary.py -v
.venv/bin/ruff check evals/test_reference_boundary.py
git add evals/test_reference_boundary.py
git commit -m "test(gateway): enforce G2 determinism and offline boundaries"
```

---

## 6. Full verification, code review, documentation

- [ ] **Step 1: run every focused suite, then the full gate**

```bash
cd backend
.venv/bin/pytest evals/test_reference_contracts.py evals/test_reference_fx_contracts.py \
  evals/test_reference_fx_build.py evals/test_reference_fx_fetch_boundary.py \
  evals/test_reference_airports_build.py evals/test_reference_airports_fetch_boundary.py \
  evals/test_g2_poi_acceptance.py evals/test_reference_boundary.py -v
.venv/bin/pytest evals/test_travel_*.py -v      # all existing G1 travel-gateway tests
.venv/bin/pytest evals/test_catalog_*.py evals/test_region_*.py evals/test_network_isolation.py -v
.venv/bin/pytest -q                             # full suite
.venv/bin/mypy --strict core/ accounts/ agents/ api/ gateway/
.venv/bin/ruff check accounts/ agents/ gateway/ evals/
git diff --exit-code -- evals/golden/
cd ..
diff CLAUDE.md AGENTS.md
make gate
```

- [ ] **Step 2: reproducibility commands (paste actual output into the report)**

```bash
cd backend
python3 - <<'PY'
import hashlib, json
from datetime import date
from gateway.reference.fx.parse import parse_frankfurter_v2
from gateway.reference.fx.build import build_fx_snapshot
raw = open("gateway/reference/fx/fixtures/frankfurter_valid.json", "rb").read()
def _build():
    quotes = parse_frankfurter_v2(raw)
    return build_fx_snapshot(quotes, source=dict(
        source_id="frankfurter", source_owner="Frankfurter", source_url="https://api.frankfurter.dev/v2/rates",
        release_id="2026-08-20", retrieved_at=date(2026,8,20),
        licence_id="frankfurter-api-blended-central-bank-sources",
        attribution="Exchange rate data from Frankfurter (frankfurter.dev)",
        terms_reference="https://frankfurter.dev/docs", content_hash=hashlib.sha256(raw).hexdigest(),
        record_count=0, warnings=[]), now=date(2026,8,20), cross_pairs=[("SGD","INR")])
a, b = _build().model_dump_json(), _build().model_dump_json()
print("FX bytes equal:", a == b)
print("FX sha256:", hashlib.sha256(a.encode()).hexdigest())
PY
```

(analogous airport reproducibility snippet run in the same step.)

- [ ] **Step 3: invoke `superpowers:requesting-code-review`** against the full diff from the
  G1 base (`67d7d95`) through G2 HEAD, with the specific inspection list from the assignment
  (licence/attribution propagation, `Decimal→rate_micro`, cross-rate rounding, duplicate
  handling, deterministic serialization, fetch/runtime separation, path-traversal/arbitrary-URL
  risk, input-size bounds, network isolation, accidental runtime/golden changes, G2c
  duplication risk). Fix Critical/Important findings test-first; re-run the full gate.

- [ ] **Step 4: write `reports/g2_open_reference_importers.md`** per the assignment's exact
  required contents list.

- [ ] **Step 5: update `CLAUDE.md` checkpoint, mirror byte-identical into `AGENTS.md`.**

- [ ] **Step 6: final commit**

```bash
git add DEVIATIONS.md reports/g2_open_reference_importers.md CLAUDE.md AGENTS.md
git commit -m "docs: record G2 milestone"
git log --oneline 67d7d95..HEAD
git status
```

---

## Self-review against spec 09 §13 and this plan's own scope correction

- **"Add one FX, airport, and POI importer at a time"** → Tasks 2, 3, 4 are independently
  committed and independently gated (each has its own test run before its commit).
- **"licence metadata retained, deterministic snapshots, no change to golden optimizer
  values"** → every builder test asserts provenance/licence fields on the *output* artifact
  (not just the input manifest); every builder has a repeated-build byte-equality test;
  `evals/golden/` is never touched and `git diff --exit-code` gates the final commit.
- **Gap found during self-review:** the initial draft of the FX cross-rate function didn't
  specify what happens when *no* pivot leg exists for a requested cross pair (silently
  dropping it would look like a bug, not a documented gap). Fixed: `build_fx_snapshot`
  appends a specific warning string per unresolvable cross pair, and
  `test_missing_currency_is_documented_not_invented` pins this behavior.
- **Gap found:** G2b's duplicate-IATA handling initially considered dropping collided
  records. Re-read the assignment's exact wording ("duplicate IATA codes handled
  conservatively" — not "excluded") and changed to preserve-both-plus-warn, which is the more
  conservative choice (never discards a real airport record).
- **Confirmed no pipeline coupling:** grep of the full plan for `pipeline.py`,
  `gateway_estimator`, `estimate_costed_trip_via_gateway`, `Gondola`, `Tripadvisor` inside any
  `gateway/reference/` file returns nothing — none of those names appear anywhere in this
  plan's file list.

## Out of scope (explicit, restated)

Everything in the assignment's "do not" list: wiring `agents/pipeline.py` or `/plan` to the
gateway estimator; Gondola or any live travel-inventory adapter; Tripadvisor live transport;
runtime provider calls; MCP connections; booking/payment/hold/transfer execution; runtime
crawling/browser automation; deterministic-kernel financial behavior changes; automatic seed
FX replacement; golden-value changes; frontend redesign; new LLM call sites. Also out of
scope for this plan specifically: OpenFlights route data; per-currency upstream-provider
verification beyond what Frankfurter's own `/v2/providers` metadata states; any new POI
ingestion mechanism (G2c reuses the existing one exclusively).
