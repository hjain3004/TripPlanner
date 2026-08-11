"""MANUAL, OFFLINE catalog input fetcher. Not imported by any test. Not run in CI.

Run once by a human, then commit only the resulting checksums to
gateway/catalog/fixtures/manifest_sg.yaml — never the raw extracts (size/licence policy,
spec 6). Requires DuckDB installed system-wide; DuckDB is deliberately NOT a project
dependency, so its extension attack surface (spec 10) stays out of the tested pipeline.

Zero-spend: Overture is published on a free public bucket. This script must never call a
paid API, and must never be wired into the request path.
"""

import subprocess
import sys
from pathlib import Path

def fetch_overture() -> None:
    print("Fetching Overture Maps data for Singapore...")
    # Bounding box for SG: ~ 103.6, 1.15, 104.1, 1.48
    query = """
    COPY (
        SELECT id, names, categories, geometry
        FROM read_parquet('s3://overturemaps-us-west-2/release/2024-03-12-alpha.0/theme=places/type=place/*', filename=true, hive_partitioning=1)
        WHERE bbox.minx >= 103.6 AND bbox.maxx <= 104.1
          AND bbox.miny >= 1.15 AND bbox.maxy <= 1.48
    ) TO 'overture_sg.json' (FORMAT JSON, ARRAY TRUE);
    """
    
    print("Execute this in DuckDB:")
    print(query)

if __name__ == "__main__":
    fetch_overture()
