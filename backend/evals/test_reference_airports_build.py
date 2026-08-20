from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from gateway.reference.airports.build import build_airport_snapshot
from gateway.reference.airports.errors import AirportImportError
from gateway.reference.airports.parse import parse_ourairports_csv

FIXTURES = Path(__file__).parent.parent / "gateway" / "reference" / "airports" / "fixtures"


def _raw(name: str) -> bytes:
    return (FIXTURES / f"{name}.csv").read_bytes()


def _source(raw: bytes, record_count: int) -> dict:
    return dict(
        source_id="ourairports",
        source_owner="OurAirports (David Megginson)",
        source_url="https://davidmegginson.github.io/ourairports-data/airports.csv",
        release_id=f"2026-08-20:{hashlib.sha256(raw).hexdigest()[:12]}",
        retrieved_at=date(2026, 8, 20),
        licence_id="public-domain",
        attribution=(
            "Airport data courtesy of OurAirports (ourairports.com), "
            "released to the Public Domain."
        ),
        terms_reference="https://ourairports.com/data/",
        content_hash=hashlib.sha256(raw).hexdigest(),
        record_count=record_count,
        warnings=[],
    )


def test_valid_fixture_produces_normalized_records_for_all_seven_corridor_airports() -> None:
    raw = _raw("ourairports_sample")
    rows = parse_ourairports_csv(raw)
    snapshot = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert snapshot.airports
    by_iata = {a.iata_code: a for a in snapshot.airports if a.iata_code}
    for code in ("DEL", "BOM", "SIN", "DXB", "LHR", "CDG", "JFK"):
        assert code in by_iata, f"missing corridor airport {code}"
    assert by_iata["DEL"].name == "Indira Gandhi International Airport"
    assert by_iata["DEL"].lat == pytest.approx(28.5665)
    assert by_iata["SIN"].scheduled_service is True


def test_missing_optional_fields_stay_none_not_fabricated() -> None:
    raw = _raw("ourairports_missing_optional")
    rows = parse_ourairports_csv(raw)
    snapshot = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    airport = snapshot.airports[0]
    assert airport.elevation_ft is None
    assert airport.gps_code is None
    assert airport.home_link is None


def test_invalid_coordinates_are_rejected() -> None:
    raw = _raw("ourairports_invalid_coordinates")
    rows = parse_ourairports_csv(raw)
    with pytest.raises(AirportImportError) as exc_info:
        build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert exc_info.value.code == "invalid_response"


def test_duplicate_stable_id_is_rejected() -> None:
    raw = _raw("ourairports_duplicate_id")
    rows = parse_ourairports_csv(raw)
    with pytest.raises(AirportImportError) as exc_info:
        build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert exc_info.value.code == "invalid_response"


def test_duplicate_iata_code_is_handled_conservatively_not_dropped() -> None:
    raw = _raw("ourairports_duplicate_iata")
    rows = parse_ourairports_csv(raw)
    snapshot = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    matching = [a for a in snapshot.airports if a.iata_code == "DEL"]
    assert len(matching) == 2
    assert any("DEL" in w for w in snapshot.provenance.warnings)


def test_uppercase_normalization_of_codes() -> None:
    raw = _raw("ourairports_sample")
    rows = parse_ourairports_csv(raw)
    snapshot = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert all(
        a.iso_country is None or a.iso_country == a.iso_country.upper() for a in snapshot.airports
    )
    assert all(a.iata_code is None or a.iata_code == a.iata_code.upper() for a in snapshot.airports)


def test_stable_deterministic_ordering() -> None:
    raw = _raw("ourairports_sample")
    rows = parse_ourairports_csv(raw)
    snapshot1 = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    snapshot2 = build_airport_snapshot(list(reversed(rows)), source=_source(raw, len(rows)))
    order1 = [(a.iso_country, a.ident) for a in snapshot1.airports]
    order2 = [(a.iso_country, a.ident) for a in snapshot2.airports]
    assert order1 == order2 == sorted(order1)


def test_repeated_build_is_byte_identical() -> None:
    raw = _raw("ourairports_sample")
    rows = parse_ourairports_csv(raw)
    s1 = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    s2 = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert s1.model_dump_json() == s2.model_dump_json()


def test_licence_and_provenance_are_retained() -> None:
    raw = _raw("ourairports_sample")
    rows = parse_ourairports_csv(raw)
    snapshot = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert snapshot.provenance.licence_id == "public-domain"
    assert "OurAirports" in snapshot.provenance.attribution
    assert snapshot.provenance.content_hash == hashlib.sha256(raw).hexdigest()


def test_input_size_and_record_count_bounds_are_enforced() -> None:
    huge_csv = (
        "id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,iso_country,"
        "iso_region,municipality,scheduled_service,gps_code,icao_code,iata_code,local_code,"
        "home_link,wikipedia_link,keywords\n" + "1,AAAA,small_airport,X,0,0,,,,,,no,,,,,,\n" * 6000
    ).encode()
    with pytest.raises(AirportImportError) as exc_info:
        parse_ourairports_csv(huge_csv, max_records=5000)
    assert exc_info.value.code == "invalid_response"


def test_zero_network_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("airport build must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    raw = _raw("ourairports_sample")
    rows = parse_ourairports_csv(raw)
    snapshot = build_airport_snapshot(rows, source=_source(raw, len(rows)))
    assert snapshot.airports
