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
    max_bytes: 5000
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

    # Create a valid zip with one valid claim (not enough for quality gate)
    import json
    import zipfile
    
    zip_path = tmp_path / "dummy.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        from gateway.catalog.quality import _MIN_PER_CATEGORY
        places = []
        idx = 1
        for cat, min_count in _MIN_PER_CATEGORY.items():
            for _ in range(min_count):
                places.append({
                    "id": f"ext_{idx}",
                    "names": {"primary": f"Place {idx}"},
                    "categories": {"primary": "zoo" if cat == "attraction" else cat},
                    "geometry": {"lat": 1.3, "lon": 103.8}
                })
                idx += 1
        z.writestr("data.json", json.dumps(places))
        
    payload = zip_path.read_bytes()

    # Update checksum in manifest to match this payload
    import hashlib

    true_checksum = hashlib.sha256(payload).hexdigest()
    bad_checksum = "0" * 64
    m.write_text(manifest_yaml.replace("abc", true_checksum))
    thin.write_text(manifest_yaml.replace("abc", true_checksum))
    bad.write_text(manifest_yaml.replace("abc", bad_checksum))

    # write raw payload
    raw_file = raw / "overture_sg_1.zip"
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
    
    # Create a new RAW directory that fails quality
    import json
    import zipfile
    
    fail_raw = tmp_path / "fail_raw"
    fail_raw.mkdir()
    
    zip_path = tmp_path / "fail_dummy.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        places = [{
            "id": "ext_1",
            "names": {"primary": "Single Place"},
            "categories": {"primary": "park"},
            "geometry": {"lat": 1.3, "lon": 103.8}
        }]
        z.writestr("data.json", json.dumps(places))
        
    payload = zip_path.read_bytes()
    
    import hashlib
    true_checksum = hashlib.sha256(payload).hexdigest()
    
    thin2 = tmp_path / "thin2.yaml"
    old_chk = THIN.read_text().split('checksum: "')[1].split('"')[0]
    thin2.write_text(THIN.read_text().replace(old_chk, true_checksum))
    
    raw_file = fail_raw / "overture_sg_1.zip"
    raw_file.write_bytes(payload)

    artifact = build_catalog(thin2, fail_raw, tmp_path / "work2")
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
