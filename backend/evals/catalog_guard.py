"""Explicit handling of the untracked regional catalog artifacts.

The regional place catalogs (``backend/catalogs/active_*-core.json``, ~140 MB, derived
from Overture Maps) are deliberately not committed. A clean clone therefore cannot run
the handful of tests that assert on their real content. Those tests carry the
``requires_regional_catalogs`` marker:

* artifacts present                      -> the tests run (the normal developer/gate path);
* artifacts absent                       -> the tests are SKIPPED with a visible reason, so
  a catalog-less CI run is honest about exactly what it did not verify;
* ``TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1`` and absent -> the session aborts. ``make gate``
  sets this, so the authoritative gate can never pass on a clone that lacks them.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from gateway.catalog.regions import get_region

BACKEND = Path(__file__).resolve().parent.parent
CORRIDORS = ("SIN", "BOM", "DXB", "NYC", "LON", "PAR")
REQUIRE_ENV = "TRIPWISE_REQUIRE_REGIONAL_CATALOGS"
SKIP_REASON = (
    "regional catalog artifacts (backend/catalogs/active_*-core.json) are not provisioned; "
    "see docs/DEPLOYMENT.md - 'Regional catalogs'"
)


def required_catalog_files(root: Path | None = None) -> list[Path]:
    base = (root or BACKEND) / "catalogs"
    files: list[Path] = []
    for iata in CORRIDORS:
        region = get_region(iata)
        assert region is not None, iata
        files.append(base / f"active_{region.catalog_id}.json")
    return files


def missing_catalogs(root: Path | None = None) -> list[str]:
    return [p.name for p in required_catalog_files(root) if not p.is_file()]


def catalogs_required(env: Mapping[str, str] | None = None) -> bool:
    return (os.environ if env is None else env).get(REQUIRE_ENV, "").strip() == "1"
