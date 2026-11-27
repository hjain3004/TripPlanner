"""Catalog loading must not alter process-wide garbage collection."""
import gc
import json
from pathlib import Path

from gateway.places.adapters.snapshot import SnapshotPlaceAdapter, clear_snapshot_catalog_cache


def test_catalog_loading_never_freezes_process_objects(tmp_path: Path, monkeypatch) -> None:
    def fail() -> None:
        raise AssertionError("catalog loading froze the process GC heap")

    monkeypatch.setattr(gc, "freeze", fail)
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({"sources": [], "claims": [], "places": []}))
    clear_snapshot_catalog_cache()
    assert SnapshotPlaceAdapter(path)._load() == []
    clear_snapshot_catalog_cache()


def test_rank_cache_is_cleared_when_its_catalog_is_evicted(tmp_path: Path) -> None:
    from gateway.places.adapters.snapshot import _RANKED_CACHE, _cache_key

    clear_snapshot_catalog_cache()
    paths = [tmp_path / f"{index}.json" for index in range(9)]
    for path in paths:
        path.write_text(json.dumps({"sources": [], "claims": [], "places": []}))
    SnapshotPlaceAdapter(paths[0])._load()
    key = (_cache_key(paths[0]), ("food",), 0.0, 0.0, 40)
    _RANKED_CACHE[key] = ()
    for path in paths[1:]:
        SnapshotPlaceAdapter(path)._load()
    assert key not in _RANKED_CACHE
    clear_snapshot_catalog_cache()


def test_kb_load_does_not_retain_a_one_shot_statement_cache(
    tmp_path: Path, monkeypatch
) -> None:
    import sqlite3

    import core.db as db

    db_path = tmp_path / "kb.sqlite"
    db.seed_database(db_path=db_path)
    original_create_engine = db.create_engine
    engines = []

    def record_engine(*args, **kwargs):
        engine = original_create_engine(*args, **kwargs)
        engines.append(engine)
        return engine

    monkeypatch.setattr(db, "create_engine", record_engine)
    before = db.load_kb(db_path)
    assert before.cards()
    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM cards")
    after = db.load_kb(db_path)
    assert after.cards() == []
    # Each engine is used for one batch of distinct queries then discarded. Its
    # compiled cache must not hold thousands of cyclic SQLAlchemy structures.
    assert all(not engine._compiled_cache for engine in engines)
