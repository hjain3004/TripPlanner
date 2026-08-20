"""Deterministic airport snapshot builder -- pure function, no I/O.

Duplicate stable ids are a structural invariant violation (fail closed).
Duplicate IATA codes are handled conservatively: every record is preserved
(never dropped -- distinct real-world airports, or a reused code after
closure, are both legitimate), and a warning documents that the code is
no longer a reliable unique key. Airports without an IATA code are always
preserved (never excluded) since they remain legitimate reference facts.
"""

from __future__ import annotations

from gateway.reference.airports.contracts import AirportRecord, AirportSnapshot
from gateway.reference.airports.errors import AirportImportError
from gateway.reference.contracts import SourceProvenance


def _optional(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _optional_float(value: str | None) -> float | None:
    text = _optional(value)
    return float(text) if text is not None else None


def _optional_int(value: str | None) -> int | None:
    text = _optional(value)
    return int(float(text)) if text is not None else None


def build_airport_snapshot(
    rows: list[dict[str, str]], *, source: dict[str, object]
) -> AirportSnapshot:
    seen_ids: set[str] = set()
    iata_counts: dict[str, int] = {}
    records: list[AirportRecord] = []
    source_warnings = source.get("warnings", [])
    warnings: list[str] = list(source_warnings) if isinstance(source_warnings, list) else []

    for row in rows:
        row_id = row["id"].strip()
        if row_id in seen_ids:
            raise AirportImportError("invalid_response", f"duplicate stable id: {row_id}")
        seen_ids.add(row_id)

        iata = _optional(row.get("iata_code"))
        if iata:
            iata_counts[iata.upper()] = iata_counts.get(iata.upper(), 0) + 1

        try:
            record = AirportRecord(
                id=row_id,
                ident=row["ident"].strip(),
                airport_type=row["type"].strip(),
                name=row["name"].strip(),
                lat=_optional_float(row.get("latitude_deg")),
                lon=_optional_float(row.get("longitude_deg")),
                elevation_ft=_optional_int(row.get("elevation_ft")),
                continent=_optional(row.get("continent")),
                iso_country=_optional(row.get("iso_country")),
                iso_region=_optional(row.get("iso_region")),
                municipality=_optional(row.get("municipality")),
                scheduled_service=row["scheduled_service"].strip().lower() == "yes",
                gps_code=_optional(row.get("gps_code")),
                icao_code=_optional(row.get("icao_code")),
                iata_code=iata,
                local_code=_optional(row.get("local_code")),
                home_link=_optional(row.get("home_link")),
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise AirportImportError("invalid_response", f"malformed row {row_id}: {exc}") from exc
        records.append(record)

    for code, count in sorted(iata_counts.items()):
        if count > 1:
            warnings.append(
                f"IATA code {code} appears on {count} records; not treated as a unique key"
            )

    records.sort(key=lambda a: (a.iso_country or "", a.ident))
    provenance = SourceProvenance(
        **{**source, "record_count": len(records), "warnings": warnings}
    )
    return AirportSnapshot(provenance=provenance, airports=records)
