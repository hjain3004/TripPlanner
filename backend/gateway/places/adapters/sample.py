from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from gateway.places.contracts import (
    PartialPlaceResult,
    PlaceCandidate,
    PlaceClaim,
    PlaceSearchRequest,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class SamplePlaceAdapter:
    def __init__(self, fixture_path: Path | None = None) -> None:
        self.fixture_path = fixture_path or (FIXTURES_DIR / "sample_places.json")
        self._cache: list[dict] | None = None  # type: ignore

    def _load(self) -> list[dict]:  # type: ignore
        if self._cache is None:
            try:
                with open(self.fixture_path, encoding="utf-8") as f:
                    self._cache = json.load(f)
            except json.JSONDecodeError as e:
                from gateway.places.registry import PlaceGatewayError

                raise PlaceGatewayError("invalid_response", f"Malformed fixture: {e}") from e
        return self._cache

    def search_places(
        self, request: PlaceSearchRequest
    ) -> tuple[list[PlaceCandidate], PartialPlaceResult | None]:
        data = self._load()
        results = []
        # Use a fixed, deterministic datetime for synthetic fixtures
        now = datetime(2026, 1, 1, tzinfo=UTC)

        # Deterministic sorting (fixture maintains order)
        for row in data:
            if request.category_filters and row["category"] not in request.category_filters:
                continue
            if row.get("area_id") != request.destination_area_id:
                continue

            claims = [
                PlaceClaim(
                    place_id=row["id"],
                    field="category",
                    value=row["category"],
                    source_id="sample",
                    source_url="urn:trip:fixture:sample_places",
                    retrieved_at=now,
                    last_verified=now,
                    verified_by="sample_adapter",
                    confidence=1.0,
                    needs_verification=True,
                    licence_id="synthetic",
                ),
                PlaceClaim(
                    place_id=row["id"],
                    field="coordinates",
                    value=row["coordinates"],
                    source_id="sample",
                    source_url="urn:trip:fixture:sample_places",
                    retrieved_at=now,
                    last_verified=now,
                    verified_by="sample_adapter",
                    confidence=1.0,
                    needs_verification=True,
                    licence_id="synthetic",
                ),
            ]
            if "opening_hours" in row:
                claims.append(
                    PlaceClaim(
                        place_id=row["id"],
                        field="opening_hours",
                        value=row["opening_hours"],
                        source_id="sample",
                        source_url="urn:trip:fixture:sample_places",
                        retrieved_at=now,
                        last_verified=now,
                        verified_by="sample_adapter",
                        confidence=1.0,
                        needs_verification=True,
                        licence_id="synthetic",
                    )
                )

            results.append(
                PlaceCandidate(
                    place_id=row["id"],
                    claims=claims,
                    status="estimated",
                )
            )

        if len(results) > request.max_results:
            results = results[: request.max_results]
            return results, PartialPlaceResult(
                unresolved_needs=["More results truncated"], stop_reason="budget_exhausted"
            )

        return results, None
