"""Regression test: the real gateway/catalog/fixtures/ directory must expose
a manifest reachable by provision_region's primary lookup path for every
registered region. Singapore's only registered IATA code is "SIN"
(regions.yaml), but its manifest historically existed only as
manifest_sg.yaml -- unreachable by provision_region(destination="SIN", ...)
via either the primary (manifest_{destination.lower()}.yaml) or fallback
(manifest_{catalog_id}.yaml, i.e. manifest_sg-core.yaml) lookup path. This
is exactly the convention evals/test_catalog_provision.py's own
test_provision_region_is_idempotent already documents and exercises (it
writes its synthetic manifest to "manifest_sin.yaml" for destination="SIN").
manifest_sg.yaml is kept unchanged -- several other tests reference it by
that literal path.
"""

from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "gateway" / "catalog" / "fixtures"


def test_real_fixtures_dir_has_a_manifest_reachable_for_destination_sin() -> None:
    assert (FIXTURES_DIR / "manifest_sin.yaml").exists()


def test_manifest_sg_yaml_is_preserved_for_existing_test_references() -> None:
    assert (FIXTURES_DIR / "manifest_sg.yaml").exists()
