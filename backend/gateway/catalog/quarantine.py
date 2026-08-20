from __future__ import annotations

import hashlib
import shutil
import tarfile
import zipfile
from pathlib import Path

from gateway.catalog.manifest import PinnedSource


class QuarantineRejected(Exception):
    pass


def _reject_unsafe_members(archive: Path, budget: int) -> None:
    """Inspect archive members WITHOUT extracting. Spec 10: path traversal + zip bombs."""
    names: list[str] = []
    expanded = 0
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                names.append(info.filename)
                expanded += info.file_size
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as t:
            for member in t.getmembers():
                names.append(member.name)
                expanded += member.size
    else:
        return

    for name in names:
        p = Path(name)
        if p.is_absolute() or ".." in p.parts:
            raise QuarantineRejected(f"path traversal in archive member: {name!r}")
    if expanded > budget:
        raise QuarantineRejected(f"expanded size {expanded} exceeds budget {budget}")


def verify_and_stage(source: PinnedSource, raw_path: Path, quarantine_dir: Path) -> Path:
    actual_size = raw_path.stat().st_size
    if actual_size > source.max_bytes:
        raise QuarantineRejected(
            f"size {actual_size} exceeds max_bytes {source.max_bytes} for {source.source_id}"
        )

    digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    if digest != source.checksum:
        raise QuarantineRejected(
            f"checksum mismatch for {source.source_id}: expected {source.checksum}, got {digest}"
        )

    _reject_unsafe_members(raw_path, source.max_bytes)

    quarantine_dir.mkdir(parents=True, exist_ok=True)
    staged = quarantine_dir / f"{source.source_id}{raw_path.suffix}"
    shutil.copy2(raw_path, staged)
    return staged
