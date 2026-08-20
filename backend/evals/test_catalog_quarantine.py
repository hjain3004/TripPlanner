import hashlib
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import pytest

from gateway.catalog.manifest import PinnedSource, load_manifest
from gateway.catalog.quarantine import QuarantineRejected, verify_and_stage

FIXTURES = Path(__file__).parent.parent / "gateway" / "catalog" / "fixtures"


def _source(tmp_path: Path, payload: bytes, **over: Any) -> tuple[PinnedSource, Path]:
    raw = tmp_path / "input.jsonl"
    raw.write_bytes(payload)
    base: dict[str, Any] = dict(
        source_id="overture_sg",
        source_url="https://example.invalid/overture.jsonl",
        licence_id="CDLA-Permissive-2.0",
        source_release="2026-07-24.0",
        checksum=hashlib.sha256(payload).hexdigest(),
        max_bytes=1_000_000,
        geographic_scope="SG",
        allowed_purpose="non-commercial student prototype",
        attribution_text="(c) Overture Maps Foundation",
    )
    base.update(over)
    return PinnedSource(**base), raw


def test_manifest_loads_every_spec_11_field() -> None:
    sources = load_manifest(FIXTURES / "manifest_sg.yaml").sources
    assert sources, "fixture manifest must not be empty"
    for s in sources:
        assert s.source_url and s.licence_id and s.checksum
        assert s.attribution_text and s.allowed_purpose and s.geographic_scope


def test_matching_checksum_is_staged(tmp_path: Path) -> None:
    src, raw = _source(tmp_path, b'{"id":"a"}\n')
    staged = verify_and_stage(src, raw, tmp_path / "q")
    assert staged.exists()


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    src, raw = _source(tmp_path, b'{"id":"a"}\n', checksum="0" * 64)
    with pytest.raises(QuarantineRejected, match="checksum"):
        verify_and_stage(src, raw, tmp_path / "q")


def test_oversized_input_is_rejected_before_reading(tmp_path: Path) -> None:
    src, raw = _source(tmp_path, b"x" * 5000, max_bytes=100)
    with pytest.raises(QuarantineRejected, match="size"):
        verify_and_stage(src, raw, tmp_path / "q")


def test_zip_path_traversal_is_rejected(tmp_path: Path) -> None:
    """A member escaping the quarantine directory must never be written."""
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../../etc/passwd", "pwned")
    payload = archive.read_bytes()
    src, _ = _source(tmp_path, payload, checksum=hashlib.sha256(payload).hexdigest())
    with pytest.raises(QuarantineRejected, match="traversal"):
        verify_and_stage(src, archive, tmp_path / "q")
    assert not (tmp_path / "etc" / "passwd").exists()


def test_absolute_path_member_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "abs.tar"
    inner = tmp_path / "inner.txt"
    inner.write_text("x")
    with tarfile.open(archive, "w") as t:
        ti = t.gettarinfo(inner)
        ti.name = "/tmp/escaped.txt"
        t.addfile(ti, inner.open("rb"))
    payload = archive.read_bytes()
    src, _ = _source(tmp_path, payload, checksum=hashlib.sha256(payload).hexdigest())
    with pytest.raises(QuarantineRejected, match="traversal"):
        verify_and_stage(src, archive, tmp_path / "q")


def test_decompression_bomb_is_rejected(tmp_path: Path) -> None:
    """Declared uncompressed size over the budget is refused without extracting."""
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.txt", "0" * 10_000_000)
    payload = archive.read_bytes()
    src, _ = _source(
        tmp_path, payload, checksum=hashlib.sha256(payload).hexdigest(), max_bytes=1_000_000
    )
    with pytest.raises(QuarantineRejected, match="expanded size"):
        verify_and_stage(src, archive, tmp_path / "q")
