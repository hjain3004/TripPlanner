"""MANUAL, OFFLINE catalog input fetcher. Not imported by any test. Not run in CI.

Run once by a human per region, then commit only the resulting checksums to the
matching gateway/catalog/fixtures/manifest_<region>.yaml - never the raw extract
(size/licence policy, spec 6). Requires DuckDB installed system-wide; DuckDB is
deliberately NOT a project dependency, so its extension attack surface (spec 10)
stays out of the tested pipeline.

Zero-spend: Overture is published on a free public bucket. This script must never
call a paid API, and must never be wired into the request path.

Supersedes fetch_overture_sg.py, which only printed its query rather than running
it, and used stale bbox field names (bbox.minx/maxx/miny/maxy) that the current
Overture release schema rejects - the real field names are xmin/ymin/xmax/ymax.

Usage:
    python scripts/fetch_overture.py \
        --manifest backend/gateway/catalog/fixtures/manifest_bom.yaml \
        --out backend/raw_overture/overture_bom.json
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import yaml

QUERY_TEMPLATE = """
INSTALL httpfs;
LOAD httpfs;
SET s3_region='us-west-2';
COPY (
    SELECT id, names, categories, geometry
    FROM read_parquet(
        's3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*',
        filename=true, hive_partitioning=1
    )
    WHERE bbox.xmin >= {min_lon} AND bbox.xmax <= {max_lon}
      AND bbox.ymin >= {min_lat} AND bbox.ymax <= {max_lat}
) TO '{out_path}' (FORMAT JSON, ARRAY TRUE);
"""


def fetch_overture(bbox: dict[str, float], release: str, out_path: Path) -> None:
    query = QUERY_TEMPLATE.format(
        release=release,
        min_lon=bbox["min_lon"],
        max_lon=bbox["max_lon"],
        min_lat=bbox["min_lat"],
        max_lat=bbox["max_lat"],
        out_path=out_path,
    )
    result = subprocess.run(
        ["duckdb", "-c", query], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"duckdb query failed with exit code {result.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="skip zipping (build_catalog requires a zip staged as "
        "<source_id>_<release>.zip, so this is on by default)",
    )
    args = parser.parse_args()

    manifest = yaml.safe_load(args.manifest.read_text())
    bbox = manifest["bbox"]
    source = manifest["sources"][0]
    release = source["source_release"]

    print(f"Fetching Overture release {release} for bbox {bbox} ...")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fetch_overture(bbox, str(release), args.out)

    size = args.out.stat().st_size
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    print(f"Wrote {args.out} ({size:,} bytes)")
    print(f"sha256(raw json): {digest}")

    if not args.no_zip:
        zip_path = args.out.parent / f"{source['source_id']}_{release}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.write(args.out, arcname=args.out.name)
        zip_digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        print(f"Wrote {zip_path} ({zip_path.stat().st_size:,} bytes)")
        print(f"sha256(zip) - paste into manifest checksum: {zip_digest}")


if __name__ == "__main__":
    main()
