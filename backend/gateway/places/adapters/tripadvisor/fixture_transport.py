from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from gateway.places.adapters.tripadvisor.contracts import (
    TripadvisorLocation,
    TripadvisorSearchResponse,
)
from gateway.places.registry import PlaceGatewayError

FixtureEvidenceStatus = Literal["cached", "estimated", "stale", "verify_required"]


class FixtureMetadata(BaseModel):
    """Internal test envelope metadata parsed outside the provider wire model."""

    model_config = ConfigDict(extra="ignore")
    status: FixtureEvidenceStatus = "cached"
    captured_at: str | None = None
    reviewed_at: str | None = None
    verified_by: str = "fixture:tripadvisor_synthetic"
    is_stale: bool = False

    @field_validator("verified_by")
    @classmethod
    def verified_by_must_be_fixture_namespace(cls, value: str) -> str:
        if not value.startswith("fixture:"):
            raise ValueError("fixture verified_by must use fixture: namespace")
        return value


class FixtureTripadvisorTransport:
    """Offline test transport that replays sanitized recorded Tripadvisor fixtures."""

    def __init__(
        self,
        default_search_fixture: str = "search_locations_success.json",
        default_details_fixture: str = "location_details_success.json",
        fixtures_dir: Path | None = None,
    ) -> None:
        if fixtures_dir is None:
            fixtures_dir = Path(__file__).parent.parent.parent / "fixtures" / "tripadvisor"
        self.fixtures_dir = fixtures_dir
        self.search_fixture_name = default_search_fixture
        self.details_fixture_name = default_details_fixture
        self.last_metadata = FixtureMetadata()

    @property
    def is_live(self) -> bool:
        return False

    @property
    def last_evidence_status(self) -> FixtureEvidenceStatus:
        return self.last_metadata.status

    @property
    def last_captured_at(self) -> datetime | None:
        return self._parse_fixture_datetime(self.last_metadata.captured_at)

    @property
    def last_reviewed_at(self) -> datetime | None:
        return self._parse_fixture_datetime(self.last_metadata.reviewed_at)

    @property
    def last_verified_by(self) -> str:
        return self.last_metadata.verified_by

    def _parse_fixture_datetime(self, raw_value: str | None) -> datetime | None:
        if raw_value:
            try:
                return datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    def _read_fixture(self, name: str) -> dict[str, Any]:
        path = self.fixtures_dir / name
        if not path.exists():
            raise PlaceGatewayError("provider_unavailable", f"Fixture not found: {name}")
        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            if not isinstance(data, dict):
                raise PlaceGatewayError("invalid_response", f"Fixture {name} is not a JSON object")

            # Parse envelope metadata if present
            if "_metadata" in data and isinstance(data["_metadata"], dict):
                try:
                    self.last_metadata = FixtureMetadata.model_validate(data["_metadata"])
                except ValidationError as e:
                    if "verified_by" in str(e):
                        msg = (
                            f"Invalid non-live fixture evidence metadata in {name}: "
                            "fixture verified_by must use fixture: namespace"
                        )
                    else:
                        msg = (
                            f"Invalid non-live fixture evidence metadata in {name}: "
                            "fixture status cannot be live"
                        )
                    raise PlaceGatewayError("invalid_response", msg) from None
            else:
                self.last_metadata = FixtureMetadata()

            return data
        except json.JSONDecodeError as e:
            msg = f"Malformed JSON in fixture {name}: {e}"
            raise PlaceGatewayError("invalid_response", msg) from e

    def _check_error_payload(self, data: dict[str, Any]) -> None:
        if "status" in data and isinstance(data["status"], int):
            status = data["status"]
            detail = data.get("detail", "Tripadvisor provider error")
            if status == 401:
                raise PlaceGatewayError("authentication_failed", f"Unauthorized: {detail}")
            if status == 403:
                raise PlaceGatewayError("permission_denied", f"Forbidden: {detail}")
            if status == 429:
                raise PlaceGatewayError("rate_limited", f"Rate limited: {detail}")
            if status >= 500:
                raise PlaceGatewayError("provider_unavailable", f"Server error: {detail}")

    def search_locations(
        self,
        query: str,
        destination: str | None = None,
        category: str | None = None,
        limit: int = 10,
    ) -> TripadvisorSearchResponse:
        data = self._read_fixture(self.search_fixture_name)
        self._check_error_payload(data)
        if "data" not in data or not isinstance(data.get("data"), list):
            raise PlaceGatewayError("invalid_response", "Missing 'data' array in search response")
        resp = TripadvisorSearchResponse.model_validate(data)

        # Filter by venue query if a specific venue query is passed (avoid leaking unrelated items)
        q = (query or "").strip().lower()
        generic_terms = {
            "",
            "places",
            "attractions",
            "singapore",
            "mumbai",
            "dubai",
            "new york",
            "london",
            "paris",
            (destination or "").lower(),
        }
        if q and q not in generic_terms:
            filtered_items = []
            for item in resp.data:
                names = [n.value.lower() for n in item.location.names if n.value]
                matched = item.matched_value.lower() if item.matched_value else ""
                if any(q in n for n in names) or (matched and q in matched):
                    filtered_items.append(item)
            resp.data = filtered_items

        if limit > 0 and len(resp.data) > limit:
            resp.data = resp.data[:limit]
        return resp

    def get_location_details(self, location_id: str | int) -> TripadvisorLocation:
        data = self._read_fixture(self.details_fixture_name)
        self._check_error_payload(data)
        if "id" not in data:
            raise PlaceGatewayError("invalid_response", "Missing 'id' in location details response")
        return TripadvisorLocation.model_validate(data)
