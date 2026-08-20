from __future__ import annotations

import math
import uuid

from gateway.places.adapters.tripadvisor.budget import (
    TripadvisorBudgetExhaustedError,
    TripadvisorEntityLedger,
)
from gateway.places.adapters.tripadvisor.fixture_transport import FixtureTripadvisorTransport
from gateway.places.adapters.tripadvisor.normalize import normalize_tripadvisor_location
from gateway.places.adapters.tripadvisor.transport import TripadvisorTransport
from gateway.places.contracts import (
    PartialPlaceResult,
    PlaceCandidate,
    PlaceSearchRequest,
    validate_adapter_response,
)
from gateway.places.registry import PlaceGatewayError


class TripadvisorTerraAdapter:
    """Normalized PlaceProviderAdapter wrapping Tripadvisor Terra content services."""

    provider_id = "tripadvisor_terra"

    def __init__(
        self,
        transport: TripadvisorTransport | None = None,
        ledger: TripadvisorEntityLedger | None = None,
    ) -> None:
        self.transport: TripadvisorTransport = transport or FixtureTripadvisorTransport()
        effective_ledger: TripadvisorEntityLedger
        if self.transport.is_live:
            if ledger is None:
                msg = (
                    "Live Tripadvisor transport requires an explicitly supplied, "
                    "verified persistent billable ledger on disk"
                )
                raise ValueError(msg)
            if not isinstance(ledger, TripadvisorEntityLedger):
                msg = "Live Tripadvisor transport requires a TripadvisorEntityLedger instance"
                raise ValueError(msg)
            if not ledger.is_billable:
                msg = "Live Tripadvisor transport requires a ledger with is_billable=True"
                raise ValueError(msg)
            if ledger.is_in_memory or ledger.db_path == ":memory:":
                msg = (
                    "Live Tripadvisor transport requires a persistent on-disk "
                    "SQLite ledger (in-memory not permitted)"
                )
                raise ValueError(msg)
            effective_ledger = ledger
        else:
            effective_ledger = ledger or TripadvisorEntityLedger()
        self.ledger: TripadvisorEntityLedger = effective_ledger

    def search_places(
        self, request: PlaceSearchRequest
    ) -> tuple[list[PlaceCandidate], PartialPlaceResult | None]:
        requested_count = min(request.max_results or 10, 50)
        query_text = (request.query or "").strip()
        dest_text = (request.destination_area_id or "").strip()
        effective_query = query_text or dest_text or "places"
        first_category = request.category_filters[0] if request.category_filters else None

        # 1. Generate unique reservation ID for atomic safety accounting
        call_id = f"call_{uuid.uuid4().hex[:12]}"

        # 2. Atomic Safety Budget Reservation
        reserved = self.ledger.reserve(requested_count, call_id=call_id)
        if not reserved:
            return [], PartialPlaceResult(
                unresolved_needs=["tripadvisor_candidate_search"],
                stop_reason="budget_exhausted",
            )

        try:
            # 3. Dispatch via Transport with typed parameters
            native_resp = self.transport.search_locations(
                query=effective_query,
                destination=dest_text,
                category=first_category,
                limit=requested_count,
            )

            # 4. Reconcile actual consumed entities
            actual_count = len(native_resp.data)
            self.ledger.reconcile(call_id=call_id, actual_entities=actual_count)

            # 5. Normalize & Deduplicate Candidates
            candidates: list[PlaceCandidate] = []
            seen_pids: set[str] = set()

            ev_status = getattr(self.transport, "last_evidence_status", None)
            captured_dt = getattr(self.transport, "last_captured_at", None)
            reviewed_dt = getattr(self.transport, "last_reviewed_at", None)
            verified_by = getattr(self.transport, "last_verified_by", None)

            for item in native_resp.data:
                candidate = normalize_tripadvisor_location(
                    item.location,
                    is_live_transport=self.transport.is_live,
                    evidence_status=ev_status,
                    retrieved_at=captured_dt,
                    last_verified_at=reviewed_dt,
                    verified_by=verified_by,
                )
                if candidate.place_id in seen_pids:
                    continue
                seen_pids.add(candidate.place_id)

                # Filter by category if requested
                if request.category_filters:
                    cat_claims = [c.value for c in candidate.claims if c.field == "category"]
                    if cat_claims and not any(
                        cat in request.category_filters for cat in cat_claims
                    ):
                        continue

                candidates.append(candidate)

            # 6. Spatial sort if origin coords provided
            if request.origin_lat is not None and request.origin_lon is not None:
                o_lat: float = request.origin_lat
                o_lon: float = request.origin_lon

                def dist_fn(cand: PlaceCandidate) -> float:
                    for cl in cand.claims:
                        if cl.field == "coordinates" and isinstance(cl.value, dict):
                            lat = cl.value.get("lat")
                            lon = cl.value.get("lon")
                            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                                return math.hypot(float(lat) - o_lat, float(lon) - o_lon)
                    return float("inf")

                candidates.sort(key=dist_fn)

            for cand in candidates:
                validate_adapter_response(request, cand)

            return candidates, None

        except TripadvisorBudgetExhaustedError:
            # Budget overage detected during reconciliation
            return [], PartialPlaceResult(
                unresolved_needs=["tripadvisor_candidate_search"],
                stop_reason="budget_exhausted",
            )
        except PlaceGatewayError as e:
            if e.code in ("authentication_failed", "permission_denied", "rate_limited"):
                self.ledger.release(call_id=call_id)
            else:
                self.ledger.settle_ambiguous_failure(call_id=call_id)

            if e.code == "rate_limited":
                return [], PartialPlaceResult(
                    unresolved_needs=["tripadvisor_candidate_search"],
                    stop_reason="rate_limited",
                )
            if e.code == "timeout":
                return [], PartialPlaceResult(
                    unresolved_needs=["tripadvisor_candidate_search"],
                    stop_reason="timeout",
                )
            raise
        except Exception:
            self.ledger.settle_ambiguous_failure(call_id=call_id)
            raise
