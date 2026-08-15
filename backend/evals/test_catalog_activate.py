from pathlib import Path

import pytest

from gateway.catalog.activate import (
    ActivationRefused,
    activate,
    active_catalog_path,
)
from gateway.catalog.build import build_catalog
from gateway.catalog.quarantine import QuarantineRejected

FIXTURES = Path("raw")


@pytest.fixture
def test_manifests(tmp_path: Path):
    manifest_yaml = """
catalog_id: sg_test
catalog_release: "2026-08-01"
sources:
  - source_id: overture_sg
    source_url: "http://x"
    licence_id: "L"
    source_release: "1"
    checksum: "abc"
    max_bytes: 100
    geographic_scope: "SG"
    allowed_purpose: "non-commercial"
    attribution_text: "Overture"
"""
    m = tmp_path / "manifest.yaml"
    m.write_text(manifest_yaml)

    bad = tmp_path / "bad.yaml"
    bad.write_text(manifest_yaml.replace("abc", "000"))

    thin = tmp_path / "thin.yaml"
    thin.write_text(manifest_yaml)

    raw = tmp_path / "raw"
    raw.mkdir()

    payload = b'{"id":"a"}\n'
    # Update checksum in manifest to match this payload
    import hashlib

    true_checksum = hashlib.sha256(payload).hexdigest()
    bad_checksum = "0" * 64
    m.write_text(manifest_yaml.replace("abc", true_checksum))
    thin.write_text(manifest_yaml.replace("abc", true_checksum))
    bad.write_text(manifest_yaml.replace("abc", bad_checksum))

    # write raw payload
    raw_file = raw / "overture_sg_1.zip"
    # wait, the source is not a zip here? no, verify_and_stage takes raw_path
    # verify_and_stage in test_catalog_quarantine expects just the file payload
    # (it doesn't have to be a zip if max_bytes check passes, but wait, the plan
    # said "uncompressed size over budget...").
    raw_file.write_bytes(payload)

    return m, bad, thin, raw


def test_successful_build_becomes_the_active_catalog(tmp_path: Path, test_manifests) -> None:
    MANIFEST, BAD, THIN, RAW = test_manifests
    artifact = build_catalog(MANIFEST, RAW, tmp_path / "work")
    activate(artifact, tmp_path / "catalogs")
    active = active_catalog_path(tmp_path / "catalogs")
    assert active is not None and active.exists()


def test_a_failed_build_leaves_the_previous_catalog_active(tmp_path: Path, test_manifests) -> None:
    """Gate I3 + spec 12: 'Keep the previous catalog active; publish failed quality report.'"""
    MANIFEST, BAD, THIN, RAW = test_manifests
    good = build_catalog(MANIFEST, RAW, tmp_path / "w1")
    activate(good, tmp_path / "catalogs")
    active = active_catalog_path(tmp_path / "catalogs")
    assert active is not None
    before = active.read_bytes()

    with pytest.raises(QuarantineRejected):
        build_catalog(BAD, RAW, tmp_path / "w2")

    after_path = active_catalog_path(tmp_path / "catalogs")
    assert after_path is not None
    assert after_path.read_bytes() == before


def test_a_quality_failure_refuses_activation(tmp_path: Path, test_manifests) -> None:
    MANIFEST, BAD, THIN, RAW = test_manifests
    artifact = build_catalog(THIN, RAW, tmp_path / "work", fail_quality=True)
    assert artifact.quality.passed is False
    with pytest.raises(ActivationRefused, match="quality"):
        activate(artifact, tmp_path / "catalogs")


def test_activation_is_atomic_leaving_no_partial_file(tmp_path: Path, test_manifests) -> None:
    MANIFEST, BAD, THIN, RAW = test_manifests
    artifact = build_catalog(MANIFEST, RAW, tmp_path / "work")
    activate(artifact, tmp_path / "catalogs")
    leftovers = [p for p in (tmp_path / "catalogs").iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_the_artifact_embeds_the_full_source_manifest(tmp_path: Path, test_manifests) -> None:
    """Spec 11: 'include the activated catalog manifest in the build report.'"""
    MANIFEST, BAD, THIN, RAW = test_manifests
    artifact = build_catalog(MANIFEST, RAW, tmp_path / "work")
    assert len(artifact.sources) == 1
    for s in artifact.sources:
        assert s.attribution_text and s.licence_id and s.checksum
