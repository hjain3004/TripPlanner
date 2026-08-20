from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

DEFAULT_DISK_BUDGET_BYTES: int = 2 * 1024 * 1024 * 1024  # 2 GB default


class TileCacheManager:
    """Manages cached tile artifacts on disk with an SQLite index and LRU eviction."""

    def __init__(
        self,
        cache_dir: Path,
        max_bytes: int = DEFAULT_DISK_BUDGET_BYTES,
        db_path: Path | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.max_bytes = max_bytes
        self.db_path = db_path or (cache_dir / "tile_cache.db")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tile_cache (
                    tile_id TEXT PRIMARY KEY,
                    catalog_release TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    build_time REAL NOT NULL,
                    last_access_time REAL NOT NULL,
                    file_path TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tile_lru ON tile_cache(last_access_time ASC);"
            )

    def record_tile(
        self,
        tile_id: str,
        catalog_release: str,
        file_path: Path,
        byte_size: int | None = None,
        access_time: float | None = None,
    ) -> list[str]:
        now = time.time() if access_time is None else access_time
        size = file_path.stat().st_size if byte_size is None else byte_size
        str_path = str(file_path.resolve())

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tile_cache (
                    tile_id, catalog_release, byte_size, build_time, last_access_time, file_path
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tile_id) DO UPDATE SET
                    catalog_release=excluded.catalog_release,
                    byte_size=excluded.byte_size,
                    last_access_time=excluded.last_access_time,
                    file_path=excluded.file_path;
                """,
                (tile_id, catalog_release, size, now, now, str_path),
            )

        return self.enforce_budget()

    def touch_tile(self, tile_id: str, access_time: float | None = None) -> None:
        now = time.time() if access_time is None else access_time
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE tile_cache SET last_access_time = ? WHERE tile_id = ?",
                (now, tile_id),
            )

    def get_total_bytes(self) -> int:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(byte_size), 0) as total FROM tile_cache"
            ).fetchone()
            return int(row["total"]) if row else 0

    def list_tiles(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT tile_id, catalog_release, byte_size, build_time, "
                "last_access_time, file_path FROM tile_cache ORDER BY last_access_time DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def enforce_budget(self) -> list[str]:
        evicted: list[str] = []
        with self._get_connection() as conn:
            total_row = conn.execute(
                "SELECT COALESCE(SUM(byte_size), 0) as total FROM tile_cache"
            ).fetchone()
            total_bytes = int(total_row["total"]) if total_row else 0

            while total_bytes > self.max_bytes:
                oldest = conn.execute(
                    "SELECT tile_id, byte_size, file_path FROM tile_cache "
                    "ORDER BY last_access_time ASC LIMIT 1"
                ).fetchone()
                if not oldest:
                    break

                tid = oldest["tile_id"]
                bsize = oldest["byte_size"]
                fpath = Path(oldest["file_path"])

                try:
                    if fpath.exists():
                        fpath.unlink()
                except OSError:
                    pass

                conn.execute("DELETE FROM tile_cache WHERE tile_id = ?", (tid,))
                evicted.append(tid)
                total_bytes -= bsize

        return evicted
