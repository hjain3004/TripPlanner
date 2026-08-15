import json
import os
from pathlib import Path

from pydantic import BaseModel

from gateway.catalog.quality import QualityReport
from gateway.places.contracts import Place, PlaceClaim


class PinnedSource(BaseModel):
    attribution_text: str
    licence_id: str
    checksum: str
    id: str
    format: str
    release: str
    url: str


class CatalogArtifact(BaseModel):
    catalog_id: str
    catalog_release: str
    sources: list[PinnedSource]
    places: list[Place]
    claims: list[PlaceClaim]
    contradictions: list[list[str]]  # wait, tuple is coerced to list by JSON
    quality: QualityReport


class ActivationRefused(Exception):
    pass


class CatalogSummary(BaseModel):
    catalog_id: str
    catalog_release: str
    place_count: int
    quality_passed: bool


def canonical_json(artifact: CatalogArtifact) -> str:
    return json.dumps(
        artifact.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _summary_path(catalog_root: Path, catalog_id: str) -> Path:
    return catalog_root / f"active_{catalog_id}.summary.json"


def activate(artifact: CatalogArtifact, catalog_root: Path) -> Path:
    if not artifact.quality.passed:
        raise ActivationRefused(
            f"quality gate failed, refusing activation: {artifact.quality.failures}"
        )
    catalog_root.mkdir(parents=True, exist_ok=True)
    target = catalog_root / f"active_{artifact.catalog_id}.json"
    tmp = catalog_root / f"active_{artifact.catalog_id}.json.tmp"
    tmp.write_text(canonical_json(artifact), encoding="utf-8")
    os.replace(tmp, target)  # atomic within a filesystem

    # A small sidecar so callers who only need counts (RegionCapability) don't
    # have to parse the full catalog - which can run tens of megabytes - just
    # to read len(places).
    summary = CatalogSummary(
        catalog_id=artifact.catalog_id,
        catalog_release=artifact.catalog_release,
        place_count=len(artifact.places),
        quality_passed=artifact.quality.passed,
    )
    summary_target = _summary_path(catalog_root, artifact.catalog_id)
    summary_tmp = catalog_root / f"active_{artifact.catalog_id}.summary.json.tmp"
    summary_tmp.write_text(summary.model_dump_json(), encoding="utf-8")
    os.replace(summary_tmp, summary_target)

    return target


def active_catalog_path(catalog_root: Path, catalog_id: str) -> Path | None:
    p = catalog_root / f"active_{catalog_id}.json"
    if p.exists():
        return p
    return None


def active_catalog_summary(catalog_root: Path, catalog_id: str) -> CatalogSummary | None:
    p = _summary_path(catalog_root, catalog_id)
    if not p.exists():
        return None
    return CatalogSummary.model_validate_json(p.read_text(encoding="utf-8"))


def list_active_catalogs(catalog_root: Path) -> list[CatalogSummary]:
    if not catalog_root.exists():
        return []
    return [
        CatalogSummary.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(catalog_root.glob("active_*.summary.json"))
    ]
