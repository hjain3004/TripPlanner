"""Manual, offline developer command. NOT imported by any test, by core/, agents/,
api/, or any request path.

Usage: python -m gateway.reference.airports.fetch --out /tmp/ourairports_snapshot.csv
"""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

ALLOWED_HOST = "davidmegginson.github.io"
AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"


def fetch(out_path: Path) -> None:
    if ALLOWED_HOST not in AIRPORTS_URL:
        raise RuntimeError("refusing to fetch from a non-allowlisted host")
    with urllib.request.urlopen(AIRPORTS_URL, timeout=30) as resp:  # noqa: S310
        out_path.write_bytes(resp.read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    fetch(args.out)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
