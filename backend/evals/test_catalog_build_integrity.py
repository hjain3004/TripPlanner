import json
import zipfile

import pytest

from gateway.catalog.build import CatalogBuildError, build_catalog


def test_a_manifest_yielding_no_claims_refuses_to_build(tmp_path):
    manifest_yaml = """
catalog_id: sg_empty
catalog_release: "2026-08-01"
sources:
  - source_id: overture_sg
    source_url: "http://x"
    licence_id: "L"
    source_release: "1"
    checksum: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    max_bytes: 100
    geographic_scope: "SG"
    allowed_purpose: "non-commercial"
    attribution_text: "Overture"
"""
    m = tmp_path / "manifest.yaml"
    m.write_text(manifest_yaml)

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "overture_sg_1.zip").write_bytes(b'')

    with pytest.raises(CatalogBuildError, match="overture_sg"):
        build_catalog(m, raw, tmp_path / "work")

def test_no_place_is_fabricated(tmp_path):
    manifest_yaml = """
catalog_id: sg_small
catalog_release: "2026-08-01"
sources:
  - source_id: overture_sg
    source_url: "http://x"
    licence_id: "L"
    source_release: "1"
    checksum: "d41d8cd98f00b204e9800998ecf8427e"
    max_bytes: 5000
    geographic_scope: "SG"
    allowed_purpose: "non-commercial"
    attribution_text: "Overture"
"""
    # Wait, the zip file needs a real checksum if we create it dynamically.
    # Actually, we can just compute the checksum dynamically.
    
    raw = tmp_path / "raw"
    raw.mkdir()
    
    zip_path = raw / "overture_sg_1.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        # overture places need id, names, categories, etc

        # write one place for each minimum category
        places = []
        from gateway.catalog.quality import _MIN_PER_CATEGORY
        idx = 1
        for cat, min_count in _MIN_PER_CATEGORY.items():
            for _ in range(min_count):
                places.append({
                    "id": f"ext_{idx}",
                    "names": {"primary": f"Place {idx}"},
                    "categories": {"primary": cat},
                    "geometry": {"type": "Point", "coordinates": [103.8, 1.3]}
                })
                idx += 1
                
        z.writestr("data.json", json.dumps(places))
        
    import hashlib
    chk = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    
    m = tmp_path / "manifest.yaml"
    m.write_text(manifest_yaml.replace("d41d8cd98f00b204e9800998ecf8427e", chk))

    artifact = build_catalog(m, raw, tmp_path / "work")
    assert len(artifact.places) > 0, "anti-vacuity: fixture must produce places"
    for p in artifact.places:
        assert len(p.external_ids) > 0, f"Fabricated place found: {p.place_id}"

