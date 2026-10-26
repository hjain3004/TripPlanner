from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2


def migrate(connection: sqlite3.Connection, schema_sql: str) -> None:
    """Apply only known, forward-compatible ingestion schema versions."""
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"unsupported ingestion schema version {version}")
    connection.executescript(schema_sql)
    if version < 2:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(review_decisions)")}
        if "request_fingerprint" not in columns:
            connection.execute(
                "ALTER TABLE review_decisions ADD COLUMN request_fingerprint "
                "TEXT NOT NULL DEFAULT ''"
            )
    if version < SCHEMA_VERSION:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
