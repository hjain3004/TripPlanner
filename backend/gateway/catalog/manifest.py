from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class PinnedSource(BaseModel):
    source_id: str
    source_url: str
    licence_id: str
    source_release: str
    checksum: str = Field(min_length=64, max_length=64)
    max_bytes: int = Field(gt=0)
    geographic_scope: str
    allowed_purpose: str
    attribution_text: str


class CatalogManifest(BaseModel):
    catalog_id: str
    catalog_release: str
    sources: list[PinnedSource] = Field(min_length=1)


def load_manifest(path: Path) -> list[PinnedSource]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return CatalogManifest.model_validate(raw).sources
