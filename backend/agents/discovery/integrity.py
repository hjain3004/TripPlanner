from typing import Any

from agents.discovery.contracts import DiscoveryCandidate


class UnknownCandidate(Exception):
    pass


def assert_ids_returned_by_gateway(proposed_ids: list[str], returned_ids: set[str]) -> None:
    for pid in proposed_ids:
        if pid not in returned_ids:
            raise UnknownCandidate(f"Candidate {pid} was not returned by the gateway.")


def resolve_discovery_candidate(candidate: DiscoveryCandidate, registry: Any) -> DiscoveryCandidate:
    # find in gateway
    c = registry.lookup_exact_or_alias(candidate.mentioned_name)
    if not c:
        candidate.resolved_place_id = None
        candidate.verification_state = "unresolved"
        return candidate
        
    # check minimum evidence (coordinates and name)
    has_coords = any(cl.field == "coordinates" for cl in getattr(c, "claims", []))
    has_name = any(cl.field == "name" for cl in getattr(c, "claims", []))
    
    if not has_coords or not has_name:
        candidate.resolved_place_id = None
        candidate.verification_state = "unresolved"
        return candidate

    candidate.resolved_place_id = c.place_id
    candidate.verification_state = "verified"
    return candidate
