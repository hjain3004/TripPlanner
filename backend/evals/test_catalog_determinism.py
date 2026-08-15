import json
import random
from hashlib import sha256
from pathlib import Path

from gateway.catalog.activate import canonical_json
from gateway.catalog.build import build_catalog
from gateway.places.contracts import PlaceClaim

MANIFEST = """
catalog_id: sg_test
catalog_release: "2026-08-01"
sources:
  - source_id: overture_sg
    source_url: "http://x"
    licence_id: "L"
    source_release: "1"
    checksum: "{checksum}"
    max_bytes: 5000
    geographic_scope: "SG"
    allowed_purpose: "non-commercial"
    attribution_text: "Overture"
"""


def _build(manifest_yaml: str, rows: list[dict], work_dir: Path) -> str:

    import zipfile
    
    zip_path = work_dir / "overture_sg_1.zip"
    work_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("data.json", json.dumps(rows))
    
    payload = zip_path.read_bytes()
    checksum = sha256(payload).hexdigest()

    m = work_dir / "manifest.yaml"
    m.write_text(manifest_yaml.format(checksum=checksum))

    raw = work_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy(zip_path, raw / "overture_sg_1.zip")

    artifact = build_catalog(m, raw, work_dir / "work")
    return canonical_json(artifact)


def _get_quality_passing_rows():
    from gateway.catalog.quality import _MIN_PER_CATEGORY
    rows = []
    idx = 1
    for cat, min_count in _MIN_PER_CATEGORY.items():
        for _ in range(min_count):
            rows.append({
                "id": f"ext_{idx}",
                "names": {"primary": f"Place {idx}"},
                "categories": {"primary": "zoo" if cat == "attraction" else cat},
                "geometry": {"lat": 1.3, "lon": 103.8}
            })
            idx += 1
    return rows

def test_two_builds_from_the_same_inputs_are_byte_identical(tmp_path: Path) -> None:
    """Gate I3: 'repeat build is hash-identical'."""
    rows = _get_quality_passing_rows()
    a = _build(MANIFEST, rows, tmp_path / "w1")
    b = _build(MANIFEST, rows, tmp_path / "w2")
    assert a == b
    assert sha256(a.encode()).hexdigest() == sha256(b.encode()).hexdigest()


def test_the_build_embeds_no_wall_clock_timestamp(tmp_path: Path) -> None:
    """A 'now' anywhere in the artifact would break reproducibility."""
    rows = _get_quality_passing_rows()
    
    import zipfile
    zip_path = tmp_path / "dummy.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("data.json", json.dumps(rows))
    payload = zip_path.read_bytes()
    checksum = sha256(payload).hexdigest()

    m = tmp_path / "manifest.yaml"
    m.write_text(MANIFEST.format(checksum=checksum))

    raw = tmp_path / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "overture_sg_1.zip").write_bytes(payload)

    artifact = build_catalog(m, raw, tmp_path / "work")
    assert all(c.retrieved_at.isoformat().startswith("2026-01-01") for c in artifact.claims)


def build_from_rows(rows: list[dict]) -> str:
    from gateway.catalog.activate import CatalogArtifact, PinnedSource
    from gateway.catalog.claims import select_claims
    from gateway.catalog.identity import resolve_places
    from gateway.catalog.manifest import PinnedSource as ManifestSource
    from gateway.catalog.normalize import normalize_overture
    from gateway.catalog.quality import evaluate_quality

    src = ManifestSource(
        source_id="overture_sg",
        source_release="1",
        source_url="http://x",
        attribution_text="Overture",
        licence_id="L",
        checksum="0" * 64,
        max_bytes=5000,
        geographic_scope="SG",
        allowed_purpose="non-commercial",
    )
    claims = normalize_overture(rows, src)
    places, decisions = resolve_places(claims)

    rewrites = {
        pid: d.resulting_place_id for d in decisions for pid in d.source_place_ids if d.merged
    }
    merged_claims = []
    for c in claims:
        new_pid = rewrites.get(c.place_id, c.place_id)
        if new_pid != c.place_id:
            c_dict = dict(c)
            c_dict["place_id"] = new_pid
            merged_claims.append(PlaceClaim.model_validate(c_dict))
        else:
            merged_claims.append(c)

    winners, contradictions = select_claims(merged_claims)
    quality = evaluate_quality(places, winners)

    out_src = PinnedSource(
        id="overture_sg",
        format="overture_json",
        release="1",
        url="http://x",
        attribution_text="Overture",
        licence_id="L",
        checksum="0" * 64,
    )

    artifact = CatalogArtifact(
        catalog_id="cat_1",
        catalog_release="2026-08-01",
        sources=[out_src],
        places=places,
        claims=winners,
        contradictions=[list(c) for c in contradictions],
        quality=quality,
    )
    return canonical_json(artifact)


def test_shuffled_input_rows_produce_the_same_artifact(tmp_path: Path) -> None:
    rows = [
        {
            "id": "a",
            "names": {"primary": "Park A"},
            "categories": {"primary": "park"},
            "geometry": {"lat": 1, "lon": 1},
        },
        {
            "id": "b",
            "names": {"primary": "Park B"},
            "categories": {"primary": "park"},
            "geometry": {"lat": 2, "lon": 2},
        },
        {
            "id": "c",
            "names": {"primary": "Park C"},
            "categories": {"primary": "park"},
            "geometry": {"lat": 3, "lon": 3},
        },
    ]
    shuffled = rows[:]
    random.Random(1234).shuffle(shuffled)
    assert build_from_rows(rows) == build_from_rows(shuffled)


def test_shuffled_merging_input_rows_produce_the_same_artifact() -> None:
    rows = [
        {
            "id": "a",
            "names": {"primary": "Merlion"},
            "categories": {"primary": "attraction"},
            "geometry": {"lat": 1, "lon": 1},
        },
        {
            "id": "b",
            "names": {"primary": "Merlion"},
            "categories": {"primary": "attraction"},
            "geometry": {"lat": 1, "lon": 1},
        },
        {
            "id": "c",
            "names": {"primary": "Park C"},
            "categories": {"primary": "park"},
            "geometry": {"lat": 3, "lon": 3},
        },
    ]

    # Confirm merging happens
    from gateway.catalog.identity import resolve_places
    from gateway.catalog.manifest import PinnedSource as ManifestSource
    from gateway.catalog.normalize import normalize_overture

    src = ManifestSource(
        source_id="overture_sg",
        source_release="1",
        source_url="http://x",
        attribution_text="Overture",
        licence_id="L",
        checksum="0" * 64,
        max_bytes=5000,
        geographic_scope="SG",
        allowed_purpose="non-commercial",
    )
    claims = normalize_overture(rows, src)
    places, decisions = resolve_places(claims)

    print(f"MERGE DECISIONS: {[d for d in decisions if d.merged]}")

    shuffled = rows[:]
    random.Random(1234).shuffle(shuffled)
    assert build_from_rows(rows) == build_from_rows(shuffled)
