from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gateway.catalog.activate import activate, active_catalog_summary
from gateway.catalog.build import build_catalog, build_catalog_tiles
from gateway.catalog.cache import TileCacheManager
from gateway.catalog.regions import get_region

_DEFAULT_MANIFEST_DIR = Path(__file__).parent / "fixtures"
_DEFAULT_RAW_DIR = Path(__file__).parent.parent.parent.parent / "raw_data"
_DEFAULT_CATALOG_ROOT = Path(__file__).parent.parent.parent / "catalogs"


def provision_region(
    destination: str,
    catalog_root: Path = _DEFAULT_CATALOG_ROOT,
    raw_dir: Path = _DEFAULT_RAW_DIR,
    work_dir: Path | None = None,
    manifest_dir: Path | None = None,
    force: bool = False,
    step: float = 0.1,
) -> dict[str, Any]:
    region = get_region(destination)
    if region is None:
        raise ValueError(f"Unknown destination region: {destination}")

    m_dir = manifest_dir or _DEFAULT_MANIFEST_DIR
    manifest_path = m_dir / f"manifest_{destination.lower()}.yaml"
    if not manifest_path.exists():
        manifest_path = m_dir / f"manifest_{region.catalog_id}.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found for destination {destination}: {manifest_path}"
        )

    # Check idempotency
    if not force:
        summary = active_catalog_summary(catalog_root, catalog_id=region.catalog_id)
        if summary is not None and summary.quality_passed:
            return {
                "status": "already_provisioned",
                "region": region.iata,
                "catalog_id": region.catalog_id,
                "place_count": summary.place_count,
            }

    if work_dir is None:
        work_dir = catalog_root / ".work" / region.catalog_id
    work_dir.mkdir(parents=True, exist_ok=True)

    # Build full catalog artifact
    artifact = build_catalog(manifest_path, raw_dir, work_dir)
    active_path = activate(artifact, catalog_root)

    # Build tiles and register into cache
    tiles_dir = catalog_root / "tiles"
    tile_paths = build_catalog_tiles(
        manifest_path, raw_dir, work_dir, tiles_dir, step=step
    )

    cache_mgr = TileCacheManager(cache_dir=tiles_dir)
    for tid, tpath in tile_paths.items():
        cache_mgr.record_tile(
            tile_id=tid,
            catalog_release=str(artifact.catalog_release),
            file_path=tpath,
        )

    return {
        "status": "provisioned",
        "region": region.iata,
        "catalog_id": region.catalog_id,
        "place_count": len(artifact.places),
        "tiles": sorted(tile_paths.keys()),
        "active_path": str(active_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lazy offline provisioning for place catalogs."
    )
    parser.add_argument(
        "--destination",
        required=True,
        help="Destination IATA code (e.g. BOM, SIN, NYC)",
    )
    parser.add_argument(
        "--catalogs-dir",
        type=Path,
        default=_DEFAULT_CATALOG_ROOT,
        help="Target catalog directory",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=_DEFAULT_RAW_DIR,
        help="Raw data directory",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Working scratch directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild even if already provisioned",
    )

    args = parser.parse_args()

    result = provision_region(
        destination=args.destination.upper(),
        catalog_root=args.catalogs_dir,
        raw_dir=args.raw_dir,
        work_dir=args.work_dir,
        force=args.force,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
