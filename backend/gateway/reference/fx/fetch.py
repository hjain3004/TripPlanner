"""Manual, offline developer command. NOT imported by any test, by core/, agents/,
api/, or any request path. Run by a human, occasionally, to refresh the FX fixture
snapshot for review -- mirrors scripts/fetch_overture.py's pattern.

Usage: python -m gateway.reference.fx.fetch --out /tmp/frankfurter_snapshot.json
"""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

ALLOWED_HOST = "api.frankfurter.dev"
FX_URL = "https://api.frankfurter.dev/v2/rates?base=USD&quotes=AED,INR,SGD"


def fetch(out_path: Path) -> None:
    if ALLOWED_HOST not in FX_URL:
        raise RuntimeError("refusing to fetch from a non-allowlisted host")
    with urllib.request.urlopen(FX_URL, timeout=10) as resp:  # noqa: S310
        out_path.write_bytes(resp.read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    fetch(args.out)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
