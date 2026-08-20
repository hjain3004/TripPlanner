from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

BACKEND = Path(__file__).parent.parent
REFERENCE_DIR = BACKEND / "gateway" / "reference"


def _imports_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_core_never_imports_gateway_reference() -> None:
    offenders = [
        str(p)
        for p in (BACKEND / "core").rglob("*.py")
        if any(n == "gateway" or n.startswith("gateway.") for n in _imports_in(p))
    ]
    assert offenders == []


def test_agents_and_api_never_import_reference_fetch_modules() -> None:
    offenders = []
    for pkg in ("agents", "api"):
        for p in (BACKEND / pkg).rglob("*.py"):
            names = _imports_in(p)
            if any("gateway.reference" in n and "fetch" in n for n in names):
                offenders.append(str(p))
    assert offenders == []


def test_no_secret_markers_in_reference_package() -> None:
    forbidden = ["sk_live", "api_key=", "Authorization: Bearer ", "BEGIN RSA PRIVATE KEY"]
    offenders = [
        str(p)
        for p in REFERENCE_DIR.rglob("*.py")
        if any(m in p.read_text() for m in forbidden)
    ]
    assert offenders == []


def test_full_reference_package_zero_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: parse+build both FX and airports from fixtures with sockets forbidden."""
    import hashlib
    from datetime import date

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no socket calls allowed anywhere in gateway.reference")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)

    from gateway.reference.airports.build import build_airport_snapshot
    from gateway.reference.airports.parse import parse_ourairports_csv
    from gateway.reference.fx.build import build_fx_snapshot
    from gateway.reference.fx.parse import parse_frankfurter_v2

    fx_raw = (
        BACKEND / "gateway" / "reference" / "fx" / "fixtures" / "frankfurter_valid.json"
    ).read_bytes()
    fx_quotes = parse_frankfurter_v2(fx_raw)
    fx_snapshot = build_fx_snapshot(
        fx_quotes,
        source=dict(
            source_id="frankfurter",
            source_owner="Frankfurter",
            source_url="https://api.frankfurter.dev/v2/rates",
            release_id="2026-08-20",
            retrieved_at=date(2026, 8, 20),
            licence_id="frankfurter-api-blended-central-bank-sources",
            attribution="Exchange rate data from Frankfurter (frankfurter.dev)",
            terms_reference="https://frankfurter.dev/docs",
            content_hash=hashlib.sha256(fx_raw).hexdigest(),
            record_count=0,
            warnings=[],
        ),
        now=date(2026, 8, 20),
        cross_pairs=[],
    )
    assert fx_snapshot.rates

    ap_raw = (
        BACKEND / "gateway" / "reference" / "airports" / "fixtures" / "ourairports_sample.csv"
    ).read_bytes()
    ap_rows = parse_ourairports_csv(ap_raw)
    ap_snapshot = build_airport_snapshot(
        ap_rows,
        source=dict(
            source_id="ourairports",
            source_owner="OurAirports",
            source_url="https://davidmegginson.github.io/ourairports-data/airports.csv",
            release_id="2026-08-20",
            retrieved_at=date(2026, 8, 20),
            licence_id="public-domain",
            attribution=(
                "Airport data courtesy of OurAirports (ourairports.com), "
                "released to the Public Domain."
            ),
            terms_reference="https://ourairports.com/data/",
            content_hash=hashlib.sha256(ap_raw).hexdigest(),
            record_count=0,
            warnings=[],
        ),
    )
    assert ap_snapshot.airports


def test_no_dependency_on_core_optimizer_or_pathfinder() -> None:
    """gateway/reference/ must never import the deterministic kernel modules that
    perform money/points arithmetic -- reference importers produce evidence, not
    activated financial facts."""
    offenders = []
    for p in REFERENCE_DIR.rglob("*.py"):
        names = _imports_in(p)
        if any("core.optimizer" in n or "core.transfer" in n for n in names):
            offenders.append(str(p))
    assert offenders == []
