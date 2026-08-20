"""I7 Task 9: per-region coverage report over whatever catalogs are actually
activated on disk. Deterministic content - no wall-clock timestamps, pinned
RUN_DATE like evals/report.py. Run manually:

    cd backend && .venv/bin/python -m evals.coverage_report
"""

from __future__ import annotations

import json
from pathlib import Path

from gateway.catalog.regions import Region, load_regions

BACKEND = Path(__file__).parent.parent
REGIONS_PATH = BACKEND / "gateway" / "catalog" / "fixtures" / "regions.yaml"
CATALOGS_ROOT = BACKEND / "catalogs"
REPORT_PATH = Path(__file__).parent.parent.parent / "reports" / "i7_coverage.md"
RUN_DATE = "2026-08-15"


def _catalog_row(region: Region) -> str:
    catalog_path = CATALOGS_ROOT / f"active_{region.catalog_id}.json"
    if not catalog_path.exists():
        gaps = ", ".join(_known_gaps(region)) or "none"
        return (
            f"| {region.iata} | {region.city_name} | absent | - | - | - | - | - | - | "
            f"{'yes' if region.budget_supported else 'no'} | {gaps} |"
        )

    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    places = data["places"]
    claims = data["claims"]
    quality = data["quality"]
    place_count = len(places)

    licensed_claims = sum(1 for c in claims if c.get("licence_id"))
    licence_pct = round(100 * licensed_claims / len(claims), 1) if claims else 0.0

    categorized = sum(v for v in quality["by_category"].values())
    categorized_pct = round(100 * categorized / place_count, 1) if place_count else 0.0

    coord_pct = round(
        100 * (place_count - quality["places_without_coordinates"]) / place_count, 1
    ) if place_count else 0.0
    hours_known_pct = round(
        100 * (place_count - quality["places_with_unknown_hours"]) / place_count, 1
    ) if place_count else 0.0

    category_mix = ", ".join(
        f"{k}:{v}" for k, v in sorted(quality["by_category"].items()) if v > 0
    )

    gaps = ", ".join(_known_gaps(region)) or "none"

    return (
        f"| {region.iata} | {region.city_name} | active | {place_count:,} | "
        f"{categorized_pct}% | {coord_pct}% | {hours_known_pct}% | {licence_pct}% | "
        f"{len(data['contradictions'])} | "
        f"{'yes' if region.budget_supported else 'no'} | {gaps} |\n"
        f"  <sub>category mix: {category_mix}</sub> |"
    )


def _known_gaps(region: Region) -> list[str]:
    gaps = []
    if not region.budget_supported:
        gaps.append(f"no FX/per-diem data for {region.currency}")
    return gaps


def generate_report() -> str:
    regions = load_regions(REGIONS_PATH)
    lines = [
        "# I7 Regional Coverage Report",
        "",
        f"Run date: {RUN_DATE} (pinned, not wall-clock - see evals/coverage_report.py)",
        "",
        "| IATA | City | Catalog | Places | Categorized | Has coords | Hours known "
        "| Licenced | Contradictions | Budget | Known gaps |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for region in sorted(regions.values(), key=lambda r: r.iata):
        lines.append(_catalog_row(region))
    lines.append("")
    lines.append(
        "`worldwide` remains labeled future work. Six registered regions is six "
        "regions - coverage probes, not a claim of global support (design doc section 6)."
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(generate_report(), encoding="utf-8")
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
