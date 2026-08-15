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


def canonical_json(artifact: CatalogArtifact) -> str:
    return json.dumps(
        artifact.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


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
    return target


def active_catalog_path(catalog_root: Path, catalog_id: str) -> Path | None:
    p = catalog_root / f"active_{catalog_id}.json"
    if p.exists():
        return p
    return None
