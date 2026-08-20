from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExternalId(BaseModel):
    namespace: Literal["overture", "osm:node", "osm:way", "osm:relation", "wikidata"]
    value: str

    @property
    def urn(self) -> str:
        if self.namespace.startswith("osm:"):
            return f"{self.namespace}/{self.value}"
        elif self.namespace == "wikidata":
            return f"{self.namespace}:{self.value}"
        else:
            return f"{self.namespace}:{self.value}"


class PlaceIdentityData(BaseModel):
    name: str
    category: str
    external_ids: list[ExternalId] = Field(default_factory=list)


def resolve_place_identity(
    place1: PlaceIdentityData, place2: PlaceIdentityData, distance_m: float
) -> Literal["merge", "separate", "ambiguous"]:
    """
    Resolve identity between two places.
    An automatic merge requires an exact shared external identifier, or a named rule
    combining normalized name + category + distance within a category-specific threshold.
    Ambiguous matches stay separate and surface for review.
    No fuzzy-name-only merging, ever.
    """
    urns1 = {ext.urn for ext in place1.external_ids}
    urns2 = {ext.urn for ext in place2.external_ids}
    if urns1 & urns2:
        return "merge"

    def normalize(name: str) -> str:
        return name.lower().strip()

    n1 = normalize(place1.name)
    n2 = normalize(place2.name)

    if n1 == n2 and place1.category == place2.category:
        if distance_m <= 50.0:
            return "merge"
        else:
            return "ambiguous"

    # Similar names but no shared ID -> separate or ambiguous, but NEVER merge.
    if n1 != n2:
        # Example naive similar check
        if (n1 in n2 or n2 in n1) and place1.category == place2.category:
            return "ambiguous"

    return "separate"
