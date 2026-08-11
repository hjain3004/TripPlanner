from typing import get_args

import pytest
from pydantic import ValidationError

from gateway.places.contracts import ExternalId, Place, PlaceClaim
from gateway.places.registry import SourceLicenceManifest


def test_place_holds_namespaced_external_identifiers() -> None:
    p = Place(
        place_id="pl_0001",
        external_ids=[
            ExternalId(namespace="overture", value="08f2a1"),
            ExternalId(namespace="osm", value="node/12345"),
            ExternalId(namespace="wikidata", value="Q1234"),
        ],
    )
    assert {e.namespace for e in p.external_ids} == {"overture", "osm", "wikidata"}


def test_place_rejects_an_unknown_identifier_namespace() -> None:
    """Spec 5.1 enumerates the namespaces. A typo must not silently create a new one."""
    with pytest.raises(ValidationError):
        ExternalId(namespace="tripadvisor_scraped", value="x")


def test_place_id_is_not_a_name() -> None:
    """Spec 5.1: 'Names are never primary keys.'"""
    assert "name" not in Place.model_fields


def test_accessibility_is_a_claimable_field() -> None:
    """Spec 5.2 lists accessibility as a separate claim; I2 omitted it."""
    assert "accessibility" in get_args(PlaceClaim.model_fields["field"].annotation)


def test_source_licence_manifest_records_the_full_spec_11_record() -> None:
    required = {
        "source_url", "licence_id", "source_release", "checksum",
        "retrieved_at", "geographic_scope", "allowed_purpose", "attribution_text",
    }
    assert required <= set(SourceLicenceManifest.model_fields)
