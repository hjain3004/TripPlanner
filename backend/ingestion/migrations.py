from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 4


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
    if version < 3:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(change_proposals)")}
        if "request_fingerprint" not in columns:
            connection.execute(
                "ALTER TABLE change_proposals ADD COLUMN request_fingerprint "
                "TEXT NOT NULL DEFAULT ''"
            )
    if version < 4:
        # FI3 adds only new insert-only tables.  Their DDL is already part of
        # the idempotent schema script, so this branch records the migration
        # boundary without rewriting any FI0–FI2 rows.
        connection.execute(
            "CREATE TABLE IF NOT EXISTS curators (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS activation_bundles ("
            "id TEXT PRIMARY KEY, client_event_id TEXT NOT NULL UNIQUE, "
            "request_fingerprint TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
    if version < SCHEMA_VERSION:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
