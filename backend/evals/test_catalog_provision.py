import ast
import hashlib
import json
import zipfile
from pathlib import Path

from gateway.catalog.provision import provision_region
from gateway.catalog.quality import _MIN_PER_CATEGORY


def test_agents_does_not_import_provision() -> None:
    """Boundary test: agents/ must never import the offline provisioning job."""
    agents_dir = Path(__file__).parent.parent / "agents"
    for py_file in agents_dir.glob("**/*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "provision" not in alias.name, (
                        f"{py_file} violates boundary: imports {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert "provision" not in mod, (
                    f"{py_file} violates boundary: imports from {mod}"
                )
                for alias in node.names:
                    assert alias.name != "provision", (
                        f"{py_file} violates boundary: imports {alias.name} from {mod}"
                    )


def test_provision_region_is_idempotent(tmp_path: Path) -> None:
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
catalog_id: sg-core
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
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    m_path = fixtures_dir / "manifest_sin.yaml"
    m_path.write_text(manifest_yaml, encoding="utf-8")

    catalog_root = tmp_path / "catalogs"

    # First run: provisions
    res1 = provision_region(
        destination="SIN",
        catalog_root=catalog_root,
        raw_dir=raw_dir,
        work_dir=tmp_path / "work",
        manifest_dir=fixtures_dir,
    )
    assert res1["status"] == "provisioned"
    assert res1["place_count"] > 0
    assert (catalog_root / "active_sg-core.json").exists()

    # Second run: idempotent, returns already_provisioned without rebuilding
    res2 = provision_region(
        destination="SIN",
        catalog_root=catalog_root,
        raw_dir=raw_dir,
        work_dir=tmp_path / "work",
        manifest_dir=fixtures_dir,
    )
    assert res2["status"] == "already_provisioned"
    assert res2["place_count"] == res1["place_count"]
