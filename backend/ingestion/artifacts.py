"""Content-addressed, immutable storage for ingestion evidence."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from ingestion.contracts import ImmutableArtifactRef


class ArtifactIntegrityError(ValueError):
    """Raised when an artifact reference does not match its stored bytes."""


class ContentAddressedStore:
    """Store bytes once under their SHA-256 digest.

    The store is deliberately independent from the SQLite queue. SQLite keeps
    immutable manifests and lineage; this store keeps the potentially large
    byte bodies. A pre-existing digest is accepted only when its bytes match.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.blob_root = root / "blobs"
        self.blob_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _validate_digest(digest: str) -> None:
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ArtifactIntegrityError("artifact digest must be a lowercase SHA-256")

    def _path(self, digest: str) -> Path:
        self._validate_digest(digest)
        return self.blob_root / digest[:2] / digest

    def put(self, data: bytes, *, media_type: str) -> ImmutableArtifactRef:
        digest = self._digest(data)
        path = self._path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                raise ArtifactIntegrityError(f"digest collision for {digest}")
        else:
            fd, temporary_name = tempfile.mkstemp(prefix=f".{digest}.", dir=path.parent)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    temporary.rename(path)
                except FileExistsError:
                    if path.read_bytes() != data:
                        raise ArtifactIntegrityError(f"digest collision for {digest}") from None
            finally:
                temporary.unlink(missing_ok=True)
        return ImmutableArtifactRef(
            sha256=digest,
            size_bytes=len(data),
            media_type=media_type,
            relative_path=str(path.relative_to(self.root)),
        )

    def read(self, reference: ImmutableArtifactRef) -> bytes:
        path = self._path(reference.sha256)
        if not path.exists():
            raise FileNotFoundError(path)
        data = path.read_bytes()
        if len(data) != reference.size_bytes or self._digest(data) != reference.sha256:
            raise ArtifactIntegrityError(
                f"stored artifact failed integrity check: {reference.sha256}"
            )
        return data
