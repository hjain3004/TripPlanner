"""OurAirports CSV parser -- raw bytes to plain dict rows.

Enforces byte and record-count bounds before any row-level validation.
"""

from __future__ import annotations

import csv
import io

from gateway.reference.airports.errors import AirportImportError

REQUIRED_COLUMNS = {
    "id", "ident", "type", "name", "latitude_deg", "longitude_deg", "elevation_ft",
    "continent", "iso_country", "iso_region", "municipality", "scheduled_service",
    "gps_code", "icao_code", "iata_code", "local_code", "home_link",
}
MAX_BYTES_DEFAULT = 5_000_000
MAX_RECORDS_DEFAULT = 5_000


def parse_ourairports_csv(
    raw: bytes, *, max_bytes: int = MAX_BYTES_DEFAULT, max_records: int = MAX_RECORDS_DEFAULT
) -> list[dict[str, str]]:
    if len(raw) > max_bytes:
        raise AirportImportError("invalid_response", f"payload exceeds {max_bytes} byte bound")
    text = raw.decode("utf-8", errors="strict")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
        raise AirportImportError("invalid_response", "CSV is missing required columns")

    rows: list[dict[str, str]] = []
    for row in reader:
        if len(rows) >= max_records:
            raise AirportImportError("invalid_response", f"exceeds {max_records} record bound")
        rows.append(row)
    return rows
