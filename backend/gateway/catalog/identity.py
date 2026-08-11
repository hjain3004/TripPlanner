from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from gateway.places.contracts import ExternalId, Place, PlaceClaim
from core.itinerary.compose import haversine_km


@dataclass
class MergeDecision:
    rule: str
    merged: bool
    source_place_ids: list[str]
    resulting_place_id: str | None


_MERGE_THRESHOLD_M: dict[str, int] = {
    "park": 400,
    "food_court": 60,
    "restaurant": 40,
    "cafe": 40,
    "attraction": 150,
    "museum": 100,
}
_DEFAULT_THRESHOLD_M = 75


def _normalize_name(name: str) -> str:
    n = name.casefold()
    n = re.sub(r"[^\w\s]", "", n)
    return re.sub(r"\s+", " ", n).strip()


def _get_distance_m(p1: dict[str, Any], p2: dict[str, Any]) -> float:
    return haversine_km(p1["lat"], p1["lon"], p2["lat"], p2["lon"]) * 1000.0


def _generate_place_id(external_ids: list[ExternalId]) -> str:
    joined = "|".join(sorted(f"{e.namespace}:{e.value}" for e in external_ids))
    return "pl_" + hashlib.sha256(joined.encode()).hexdigest()[:16]


def resolve_places(claims: list[PlaceClaim]) -> tuple[list[Place], list[MergeDecision]]:
    # Group claims by original place_id
    claims_by_pid: dict[str, list[PlaceClaim]] = defaultdict(list)
    for c in claims:
        claims_by_pid[c.place_id].append(c)

    # We will build components of merged pids
    # Start with each original pid in its own component
    pid_groups: list[set[str]] = [{pid} for pid in claims_by_pid]

    decisions: list[MergeDecision] = []

    # Helper to merge two groups
    def merge_groups(i: int, j: int, rule: str) -> None:
        if i == j:
            return
        pid_groups[i].update(pid_groups[j])
        pid_groups[j].clear()

    # Pass 1: exact_external_id
    # If two groups share any (namespace, value), they merge.
    # original place_id is itself an external ID (e.g. overture:xxx -> namespace overture, value xxx)
    # Plus any other external IDs. But the spec says: "sharing any (namespace, value) merge".
    # Since original place_id carries the namespace implicitly in its prefix:
    def get_ext_ids(pid: str) -> list[ExternalId]:
        res = []
        for part in pid.split("|"):
            if ":" in part:
                ns, val = part.split(":", 1)
                res.append(ExternalId(namespace=ns, value=val)) # type: ignore
        return res

    for i in range(len(pid_groups)):
        for j in range(i + 1, len(pid_groups)):
            if not pid_groups[i] or not pid_groups[j]:
                continue
            
            # Check for shared external IDs
            ext_i = set((e.namespace, e.value) for pid in pid_groups[i] for e in get_ext_ids(pid))
            ext_j = set((e.namespace, e.value) for pid in pid_groups[j] for e in get_ext_ids(pid))
            
            if ext_i & ext_j:
                decisions.append(MergeDecision(
                    rule="exact_external_id",
                    merged=True,
                    source_place_ids=sorted(list(pid_groups[i] | pid_groups[j])),
                    resulting_place_id=None # will fill later
                ))
                merge_groups(i, j, "exact_external_id")

    # Clean up empty groups
    pid_groups = [g for g in pid_groups if g]

    # Pass 2 & 3: name_category_distance and ambiguous_review
    # We compare groups pairwise.
    def get_group_data(g: set[str]) -> tuple[set[str], set[str], list[dict[str, Any]]]:
        names = set()
        categories = set()
        coords = []
        for pid in g:
            for c in claims_by_pid[pid]:
                if c.field == "name":
                    names.add(_normalize_name(str(c.value)))
                elif c.field == "category":
                    categories.add(str(c.value))
                elif c.field == "coordinates":
                    coords.append(c.value)
        return names, categories, coords

    changed = True
    while changed:
        changed = False
        for i in range(len(pid_groups)):
            for j in range(i + 1, len(pid_groups)):
                if not pid_groups[i] or not pid_groups[j]:
                    continue
                
                n_i, cat_i, coord_i = get_group_data(pid_groups[i])
                n_j, cat_j, coord_j = get_group_data(pid_groups[j])
                
                # Must share at least one normalized name and one category
                shared_names = n_i & n_j
                shared_cats = cat_i & cat_j
                if not shared_names or not shared_cats:
                    continue
                
                if not coord_i or not coord_j:
                    continue
                
                # Check distances between any pair of coords
                min_dist = float('inf')
                for c1 in coord_i:
                    for c2 in coord_j:
                        min_dist = min(min_dist, _get_distance_m(c1, c2))
                
                # Category threshold (use the first shared category for threshold)
                cat = sorted(shared_cats)[0]
                threshold = _MERGE_THRESHOLD_M.get(cat, _DEFAULT_THRESHOLD_M)
                
                if min_dist <= threshold:
                    decisions.append(MergeDecision(
                        rule="name_category_distance",
                        merged=True,
                        source_place_ids=sorted(list(pid_groups[i] | pid_groups[j])),
                        resulting_place_id=None
                    ))
                    merge_groups(i, j, "name_category_distance")
                    changed = True
                    break
                elif min_dist <= 2 * threshold:
                    decisions.append(MergeDecision(
                        rule="ambiguous_review",
                        merged=False,
                        source_place_ids=sorted(list(pid_groups[i] | pid_groups[j])),
                        resulting_place_id=None
                    ))
        
        pid_groups = [g for g in pid_groups if g]

    # Generate final places and update decisions
    places: list[Place] = []
    
    # Sort groups deterministically based on original pids
    pid_groups = sorted(pid_groups, key=lambda g: sorted(list(g))[0])
    
    group_to_final_pid: dict[frozenset[str], str] = {}
    
    for g in pid_groups:
        ext_ids = []
        for pid in g:
            ext_ids.extend(get_ext_ids(pid))
        
        # Keep unique external IDs deterministically
        unique_ext_ids = []
        seen = set()
        for e in ext_ids:
            tup = (e.namespace, e.value)
            if tup not in seen:
                seen.add(tup)
                unique_ext_ids.append(e)
        
        unique_ext_ids.sort(key=lambda e: (e.namespace, e.value))
        final_pid = _generate_place_id(unique_ext_ids)
        
        places.append(Place(place_id=final_pid, external_ids=unique_ext_ids))
        group_to_final_pid[frozenset(g)] = final_pid
                
    # Update decisions with final resulting place ids (for merged ones)
    for d in decisions:
        if d.merged:
            # find which group this became part of
            for g, final_pid in group_to_final_pid.items():
                if set(d.source_place_ids).issubset(g):
                    d.resulting_place_id = final_pid
                    break

    # Re-sort places deterministically
    places.sort(key=lambda p: p.place_id)
    
    return places, decisions
