from pathlib import Path

import yaml
from pydantic import BaseModel


class Region(BaseModel):
    iata: str
    city_name: str
    country_code: str
    timezone: str
    catalog_id: str
    centroid_lat: float
    centroid_lon: float
    currency: str
    budget_supported: bool


def load_regions(path: Path) -> dict[str, Region]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {r["iata"]: Region.model_validate(r) for r in data.get("regions", [])}

# Global singleton for loaded regions
_REGIONS: dict[str, Region] | None = None

def get_region(iata: str) -> Region | None:
    global _REGIONS
    if _REGIONS is None:
        p = Path(__file__).parent / "fixtures" / "regions.yaml"
        _REGIONS = load_regions(p)
    return _REGIONS.get(iata)
