from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from core.models import Card, Offer, PointValuation, RewardRule
from ingestion.validation import _flatten

SUPPORTED_TABLES: dict[str, tuple[str, type[BaseModel]]] = {
    "cards": ("cards.yaml", Card),
    "reward_rules": ("reward_rules.yaml", RewardRule),
    "offers": ("offers.yaml", Offer),
    "point_valuations": ("point_valuations.yaml", PointValuation),
}


class SeedRowError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def flatten_row(row: dict[str, Any]) -> dict[str, Any]:
    return _flatten(row)


class SeedRowSource:
    def __init__(self, seeds_dir: Path) -> None:
        self.seeds_dir = seeds_dir

    def _raw_rows(self, table: str) -> list[dict[str, Any]]:
        spec = SUPPORTED_TABLES.get(table)
        if spec is None:
            raise SeedRowError("unsupported_target_table", f"unsupported target table: {table}")
        path = self.seeds_dir / spec[0]
        raw = yaml.safe_load(path.read_bytes())
        if not isinstance(raw, list):
            raise SeedRowError("current_row_missing", f"seed file is not a list: {path.name}")
        return [value for value in raw if isinstance(value, dict)]

    def table_rows(self, table: str) -> list[dict[str, Any]]:
        filename, model = SUPPORTED_TABLES.get(table, ("", BaseModel))
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
        filename, _model = SUPPORTED_TABLES.get(table, (None, None))
        if filename is None:
            raise SeedRowError("unsupported_target_table", f"unsupported target table: {table}")
        return hashlib.sha256((self.seeds_dir / filename).read_bytes()).hexdigest()
