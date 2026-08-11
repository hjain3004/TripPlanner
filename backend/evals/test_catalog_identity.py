from gateway.catalog.identity import resolve_places
from gateway.places.contracts import PlaceClaim


def test_shared_wikidata_id_merges_two_source_records(
    claims_sharing_wikidata: list[PlaceClaim],
) -> None:
    places, decisions = resolve_places(claims_sharing_wikidata)
    assert len(places) == 1
    namespaces = {e.namespace for e in places[0].external_ids}
    assert {"overture", "osm", "wikidata"} <= namespaces
    assert any(d.rule == "exact_external_id" for d in decisions)


def test_same_name_far_apart_does_not_merge(
    claims_same_name_far_apart: list[PlaceClaim],
) -> None:
    """Two cafes with the same brand name 4km apart are two places."""
    places, _ = resolve_places(claims_same_name_far_apart)
    assert len(places) == 2


def test_same_name_same_category_within_threshold_merges(
    claims_near_duplicate: list[PlaceClaim],
) -> None:
    places, decisions = resolve_places(claims_near_duplicate)
    assert len(places) == 1
    assert any(d.rule == "name_category_distance" for d in decisions)


def test_ambiguous_match_stays_separate_and_is_flagged(
    claims_ambiguous: list[PlaceClaim],
) -> None:
    """Spec 5.1: ambiguous matches remain separate and surface for review."""
    places, decisions = resolve_places(claims_ambiguous)
    assert len(places) == 2
    flagged = [d for d in decisions if d.rule == "ambiguous_review"]
    assert flagged and all(d.merged is False for d in flagged)


def test_every_merge_decision_is_reversible(
    claims_sharing_wikidata: list[PlaceClaim],
) -> None:
    """Spec 5.1: 'Identity resolution is deterministic and reversible.'"""
    _, decisions = resolve_places(claims_sharing_wikidata)
    merged = [d for d in decisions if d.merged]
    assert merged
    for d in merged:
        assert d.source_place_ids and d.resulting_place_id and d.rule


def test_resolution_is_order_independent(claims_near_duplicate: list[PlaceClaim]) -> None:
    a, _ = resolve_places(claims_near_duplicate)
    b, _ = resolve_places(list(reversed(claims_near_duplicate)))
    assert [p.place_id for p in a] == [p.place_id for p in b]
    assert [sorted(e.value for e in p.external_ids) for p in a] == \
           [sorted(e.value for e in p.external_ids) for p in b]


def test_names_are_never_used_as_the_primary_key(
    claims_sharing_wikidata: list[PlaceClaim],
) -> None:
    places, _ = resolve_places(claims_sharing_wikidata)
    for p in places:
        assert not p.place_id.startswith("name:")
