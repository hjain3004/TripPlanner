from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from core.itinerary.compose import haversine_km
from gateway.places.contracts import ExternalId, Place, PlaceClaim


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
    claims_by_pid: dict[str, list[PlaceClaim]] = defaultdict(list)
    for c in claims:
        claims_by_pid[c.place_id].append(c)

    def get_ext_ids(pid: str) -> list[ExternalId]:
        res = []
        for part in pid.split("|"):
            if ":" in part:
                ns, val = part.split(":", 1)
                res.append(ExternalId(namespace=ns, value=val))
        return res

    parent: dict[str, str] = {}
    def find(i: str) -> str:
        if parent[i] == i:
            return i
        parent[i] = find(parent[i])
        return parent[i]

    def union(i: str, j: str) -> bool:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j
            return True
        return False

    decisions: list[MergeDecision] = []
    
    # Pass 1: exact_external_id
    ext_id_to_pids = defaultdict(list)
    for pid in claims_by_pid:
        parent[pid] = pid
        for ext in get_ext_ids(pid):
            ext_id_to_pids[(ext.namespace, ext.value)].append(pid)

    for pids in ext_id_to_pids.values():
        for i in range(1, len(pids)):
            if union(pids[0], pids[i]):
                # It's hard to track decisions correctly with union find for exact pairs
                # The existing code added a decision per merge.
                pass
    
    # To match original behaviour of adding decisions, we can just rebuild groups
    groups = defaultdict(set)
    for pid in claims_by_pid:
        groups[find(pid)].add(pid)
    
    pid_groups = list(groups.values())
    
    # Re-add Pass 1 decisions (it merged everything in the set)
    for g in pid_groups:
        if len(g) > 1:
            decisions.append(MergeDecision(
                rule="exact_external_id",
                merged=True,
                source_place_ids=sorted(list(g)),
                resulting_place_id=None
            ))

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
        
        # Build index
        index = defaultdict(list)
        group_data = []
        for idx, g in enumerate(pid_groups):
            n, cat, coord = get_group_data(g)
            group_data.append((n, cat, coord))
            for name in n:
                for category in cat:
                    index[(name, category)].append(idx)
                    
        merged_in_this_pass: set[int] = set()
        
        for idxs in index.values():
            if len(idxs) < 2:
                continue
            for i in range(len(idxs)):
                for j in range(i + 1, len(idxs)):
                    idx_i = idxs[i]
                    idx_j = idxs[j]
                    if idx_i in merged_in_this_pass or idx_j in merged_in_this_pass:
                        continue
                    
                    n_i, cat_i, coord_i = group_data[idx_i]
                    n_j, cat_j, coord_j = group_data[idx_j]
                    
                    shared_names = n_i & n_j
                    shared_cats = cat_i & cat_j
                    if not shared_names or not shared_cats:
                        continue
                    if not coord_i or not coord_j:
                        continue
                        
                    min_dist = float('inf')
                    for c1 in coord_i:
                        for c2 in coord_j:
                            min_dist = min(min_dist, _get_distance_m(c1, c2))
                            
                    best_cat = sorted(list(shared_cats))[0]
                    threshold = _MERGE_THRESHOLD_M.get(best_cat, _DEFAULT_THRESHOLD_M)
                    
                    if min_dist <= threshold:
                        decisions.append(MergeDecision(
                            rule="name_category_distance",
                            merged=True,
                            source_place_ids=sorted(list(pid_groups[idx_i] | pid_groups[idx_j])),
                            resulting_place_id=None
                        ))
                        pid_groups[idx_i].update(pid_groups[idx_j])
                        merged_in_this_pass.add(idx_j)
                        changed = True
                        break # Break out of inner to re-index, or continue?
                    elif min_dist <= 2 * threshold:
                        decisions.append(MergeDecision(
                            rule="ambiguous_review",
                            merged=False,
                            source_place_ids=sorted(list(pid_groups[idx_i] | pid_groups[idx_j])),
                            resulting_place_id=None
                        ))
        
        if changed:
            pid_groups = [g for idx, g in enumerate(pid_groups) if idx not in merged_in_this_pass]

    places: list[Place] = []
    pid_groups = sorted(pid_groups, key=lambda g: sorted(list(g))[0])
    group_to_final_pid: dict[frozenset[str], str] = {}
    
    for g in pid_groups:
        ext_ids = []
        for pid in g:
            ext_ids.extend(get_ext_ids(pid))
        
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
                
    for d in decisions:
        if d.merged:
            for fz_g, final_pid in group_to_final_pid.items():
                if set(d.source_place_ids).issubset(fz_g):
                    d.resulting_place_id = final_pid
                    break

    places.sort(key=lambda p: p.place_id)
    return places, decisions
