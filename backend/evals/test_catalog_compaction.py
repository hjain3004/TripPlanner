import hashlib
import json
import zipfile
from pathlib import Path

from gateway.catalog.activate import activate
from gateway.catalog.build import build_catalog
from gateway.catalog.quality import _MIN_PER_CATEGORY
from gateway.places.adapters.snapshot import SnapshotPlaceAdapter


def _build_test_catalog(tmp_path: Path) -> Path:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    places = []
    idx = 1
    for cat, min_count in _MIN_PER_CATEGORY.items():
        for _ in range(min_count):
            places.append(
                {
                    "id": f"ext_{idx}",
                    "names": {"primary": f"Place {idx}"},
                    "categories": {"primary": "zoo" if cat == "attraction" else cat},
                    "geometry": {"lat": 1.35, "lon": 103.82},
                }
            )
            idx += 1

    zip_path = tmp_path / "dummy.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("data.json", json.dumps(places))

    payload = zip_path.read_bytes()
    chk = hashlib.sha256(payload).hexdigest()
    raw_file = raw_dir / "overture_sg_2026-07-22.0.zip"
    raw_file.write_bytes(payload)

    manifest_yaml = f"""
catalog_id: sg-test
catalog_release: "2026-08-01"
centroid_lat: 1.3521
centroid_lon: 103.8198
bbox:
  min_lat: 1.20
  max_lat: 1.48
  min_lon: 103.60
  max_lon: 104.09
sources:
  - source_id: overture_sg
    source_url: "https://example.com/overture-sg"
    licence_id: "CDLA-Permissive-2.0"
    source_release: "2026-07-22.0"
    checksum: "{chk}"
    max_bytes: 50000
    geographic_scope: "SG"
    allowed_purpose: "non-commercial"
    attribution_text: "Overture Maps Foundation"
"""
    m_path = tmp_path / "manifest.yaml"
    m_path.write_text(manifest_yaml, encoding="utf-8")

    artifact = build_catalog(m_path, raw_dir, tmp_path / "work")
    active_path = activate(artifact, tmp_path / "catalogs")
    return active_path


def test_serialized_artifact_stores_source_metadata_once(tmp_path: Path) -> None:
    active_path = _build_test_catalog(tmp_path)
    data = json.loads(active_path.read_text(encoding="utf-8"))

    # Sources list must contain the provenance metadata
    assert len(data.get("sources", [])) == 1
    src = data["sources"][0]
    assert src.get("url") == "https://example.com/overture-sg"
    assert src.get("licence_id") == "CDLA-Permissive-2.0"
    assert src.get("attribution_text") == "Overture Maps Foundation"
    assert src.get("release") == "2026-07-22.0"

    # Claims must NOT duplicate per-source metadata
    claims = data.get("claims", [])
    assert len(claims) > 0, "Anti-vacuity: fixture must have claims"

    duplicated_fields = {
        "source_url",
        "attribution_requirements",
        "licence_id",
        "source_release",
        "verified_by",
    }
    for claim in claims:
        for field in duplicated_fields:
            assert field not in claim, f"Claim {claim.get('place_id')} still duplicates {field}"


def test_round_trip_rehydrates_full_provenance(tmp_path: Path) -> None:
    active_path = _build_test_catalog(tmp_path)
    adapter = SnapshotPlaceAdapter(active_path)
    candidates = adapter._load()

    assert len(candidates) > 0, "Anti-vacuity: must have candidates"

    for candidate in candidates:
        assert len(candidate.claims) > 0
        for claim in candidate.claims:
            assert claim.source_id == "overture_sg"
            assert claim.source_url == "https://example.com/overture-sg"
            assert claim.licence_id == "CDLA-Permissive-2.0"
            assert claim.source_release == "2026-07-22.0"
            assert claim.attribution_requirements == "Overture Maps Foundation"
            assert claim.verified_by == "catalog:overture_sg"
            assert claim.retrieved_at is not None
            assert claim.last_verified is not None
