from pathlib import Path
import json

from gateway.places.contracts import (
    PlaceSearchRequest,
    PlaceCandidate,
    PartialPlaceResult,
    PlaceClaim,
)
from gateway.places.registry import PlaceGatewayError

class SnapshotPlaceAdapter:
    def __init__(self, catalog_path: Path):
        self.catalog_path = catalog_path
        self._cache = None
        
    def _load(self):
        if self._cache is not None:
            return self._cache
            
        if not self.catalog_path.exists():
            raise PlaceGatewayError(code="provider_unavailable", message="Catalog snapshot missing")
            
        try:
            with open(self.catalog_path, encoding="utf-8") as f:
                data = json.load(f)
                
            # create lookup for claims
            # we need to map source to licence and attribution
            source_map = {}
            for s in data.get("sources", []):
                source_map[s["id"]] = s
                
            # claims have licence_id but lack attribution text? Wait, in conftest I set attribution_requirements.
            # wait, the spec says "map claims into PlaceCandidate"
            places_claims = {}
            for c in data.get("claims", []):
                pid = c["place_id"]
                if pid not in places_claims:
                    places_claims[pid] = []
                    
                c_dict = dict(c)
                if not c_dict.get("attribution_requirements"):
                    src = source_map.get(c_dict["source_id"])
                    if src and "attribution_text" in src:
                        c_dict["attribution_requirements"] = src["attribution_text"]
                places_claims[pid].append(PlaceClaim.model_validate(c_dict))
                
            candidates = []
            for p in data.get("places", []):
                pid = p["place_id"]
                claims = places_claims.get(pid, [])
                
                # Check status
                has_hours = any(c.field == "opening_hours" for c in claims)
                needs_verify = any(getattr(c, "needs_verification", False) for c in claims)
                
                if not has_hours or needs_verify:
                    status = "verify_required"
                else:
                    status = "cached"
                    
                candidates.append(
                    PlaceCandidate(
                        place_id=pid,
                        status=status,
                        claims=claims
                    )
                )
                
            candidates.sort(key=lambda c: c.place_id)
            self._cache = candidates
            return self._cache
            
        except PlaceGatewayError:
            raise
        except Exception as e:
            raise PlaceGatewayError(code="provider_unavailable", message=str(e))

    def search_places(self, request: PlaceSearchRequest) -> tuple[list[PlaceCandidate], PartialPlaceResult | None]:
        candidates = self._load()
        
        filtered = []
        for c in candidates:
            # check category
            if request.category_filters:
                cat = next((claim.value for claim in c.claims if claim.field == "category"), None)
                if cat not in request.category_filters:
                    continue
            filtered.append(c)
            
        if len(filtered) > request.max_results:
            return filtered[:request.max_results], PartialPlaceResult(stop_reason="budget_exhausted", unresolved_needs=["budget_exhausted"])
            
        return filtered, None
