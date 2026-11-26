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
