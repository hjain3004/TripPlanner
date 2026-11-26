from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from core.models import Card, Offer, PointValuation, RewardRule
from ingestion.validation import _flatten
from welcome.models import CardAcquisitionOffer

SUPPORTED_TABLES: dict[str, tuple[str, type[BaseModel]]] = {
    "cards": ("cards.yaml", Card),
    "reward_rules": ("reward_rules.yaml", RewardRule),
    "offers": ("offers.yaml", Offer),
    "point_valuations": ("point_valuations.yaml", PointValuation),
}


# Catalogs that are reference data but not core seeds. They take part in extraction and review
# like a seed table, and are published by their own controlled publisher (welcome/publication.py),
# never through the core seed bundle.
CATALOG_TABLES: dict[str, tuple[str, type[BaseModel]]] = {
    "card_acquisition_offers": ("card_acquisition_offers.yaml", CardAcquisitionOffer),
}


class SeedRowError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def flatten_row(row: dict[str, Any]) -> dict[str, Any]:
    return _flatten(row)


def _spec(table: str) -> tuple[str, type[BaseModel]] | None:
    return SUPPORTED_TABLES.get(table) or CATALOG_TABLES.get(table)


class SeedRowSource:
    def __init__(self, seeds_dir: Path, catalog_dir: Path | None = None) -> None:
        self.seeds_dir = seeds_dir
        # Where catalog tables (the welcome offers) are read from; the shipped data by default.
        self.catalog_dir = (
            catalog_dir or Path(__file__).resolve().parent.parent / "welcome" / "data"
        )

    def _path(self, table: str) -> Path:
        spec = _spec(table)
        if spec is None:
            raise SeedRowError("unsupported_target_table", f"unsupported target table: {table}")
        base = self.catalog_dir if table in CATALOG_TABLES else self.seeds_dir
        return base / spec[0]

    def _raw_rows(self, table: str) -> list[dict[str, Any]]:
        path = self._path(table)
        raw = yaml.safe_load(path.read_bytes())
        if not isinstance(raw, list):
            raise SeedRowError("current_row_missing", f"seed file is not a list: {path.name}")
        return [value for value in raw if isinstance(value, dict)]

    def table_rows(self, table: str) -> list[dict[str, Any]]:
        filename, model = _spec(table) or ("", BaseModel)
        del filename
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in self._raw_rows(table):
            try:
                typed = model.model_validate(raw)
            except Exception as error:
                raise SeedRowError(
                    "current_row_missing", f"invalid {table} row: {error}"
                ) from error
            normalized = typed.model_dump(mode="json")
            row_id = normalized.get("id")
            if not isinstance(row_id, str):
                raise SeedRowError("current_row_missing", f"{table} row has no string id")
            if row_id in seen:
                raise SeedRowError("duplicate_row_id", f"duplicate {table} id: {row_id}")
            seen.add(row_id)
            rows.append(normalized)
        return rows

    def current_row(self, table: str, target_id: str) -> dict[str, Any]:
        for row in self.table_rows(table):
            if row.get("id") == target_id:
                return row
        raise SeedRowError("current_row_missing", f"missing {table} row: {target_id}")

    def seed_file_sha256(self, table: str) -> str:
        return hashlib.sha256(self._path(table).read_bytes()).hexdigest()
