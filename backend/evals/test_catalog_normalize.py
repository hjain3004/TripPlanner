import json
from pathlib import Path
from typing import Any

from gateway.catalog.manifest import PinnedSource, load_manifest
from gateway.catalog.normalize import normalize_overture, normalize_wikivoyage

FIXTURES = Path(__file__).parent.parent / "gateway" / "catalog" / "fixtures"


def _source(source_id: str) -> PinnedSource:
    return next(
        s for s in load_manifest(FIXTURES / "manifest_sg.yaml") if s.source_id == source_id
    )


def _overture_rows() -> list[dict[str, Any]]:
    with open(FIXTURES / "overture_sg_sample.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_every_claim_carries_the_licence_of_its_source() -> None:
    claims = normalize_overture(_overture_rows(), _source("overture_sg"))
    assert claims
    assert all(c.licence_id == "CDLA-Permissive-2.0" for c in claims)
    assert all(c.attribution_requirements == "(c) Overture Maps Foundation" for c in claims)


def test_coordinates_and_category_are_separate_claims() -> None:
    """Spec 5.2: separate claims, because freshness policy differs by meaning."""
    claims = normalize_overture(_overture_rows(), _source("overture_sg"))
    first = claims[0].place_id
    fields = {c.field for c in claims if c.place_id == first}
    assert {"coordinates", "category", "name"} <= fields


def test_source_release_is_recorded_on_every_claim() -> None:
    claims = normalize_overture(_overture_rows(), _source("overture_sg"))
    assert all(c.source_release == "2026-07-22.0" for c in claims)


def test_missing_hours_produce_no_hours_claim_rather_than_an_open_one() -> None:
    """Spec 5.4: 'Unknown hours do not magically become open.'"""
    rows: list[dict[str, Any]] = [
        {"id": "x1", "names": {"primary": "No Hours Place"},
         "categories": {"primary": "park"}, "geometry": {"lat": 1.0, "lon": 103.0}}
    ]
    claims = normalize_overture(rows, _source("overture_sg"))
    assert not [c for c in claims if c.field == "opening_hours"]


def test_wikivoyage_text_is_sanitized_through_the_pipeline() -> None:
    with open(FIXTURES / "wikivoyage_sg_sample.json", encoding="utf-8") as f:
        rows = json.load(f)
    claims = normalize_wikivoyage(rows, _source("wikivoyage_sg"))
    blob = " ".join(str(c.value) for c in claims).lower()
    assert "<script" not in blob
    assert "ignore all previous" not in blob
    assert "historic district" in blob


def test_normalization_output_order_is_stable() -> None:
    rows = _overture_rows()
    a = normalize_overture(rows, _source("overture_sg"))
    b = normalize_overture(list(reversed(rows)), _source("overture_sg"))
    assert [(c.place_id, c.field) for c in a] == [(c.place_id, c.field) for c in b]
