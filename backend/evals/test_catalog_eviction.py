from pathlib import Path

from gateway.catalog.cache import TileCacheManager


def test_lru_eviction_bounds_disk_budget(tmp_path: Path) -> None:
    cache_dir = tmp_path / "tiles"
    cache_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cache.db"

    # Budget of 700 bytes: each tile is 300 bytes -> max 2 tiles
    mgr = TileCacheManager(cache_dir=cache_dir, max_bytes=700, db_path=db_path)

    # Create tile 1 (300 bytes)
    t1_path = cache_dir / "tile_1.json"
    t1_path.write_bytes(b"x" * 300)
    mgr.record_tile("tile_1", "2026-08-01", t1_path, access_time=100.0)

    # Create tile 2 (300 bytes)
    t2_path = cache_dir / "tile_2.json"
    t2_path.write_bytes(b"x" * 300)
    mgr.record_tile("tile_2", "2026-08-01", t2_path, access_time=200.0)

    assert mgr.get_total_bytes() == 600
    assert t1_path.exists()
    assert t2_path.exists()

    # Touch tile 1 to make it newer than tile 2
    mgr.touch_tile("tile_1", access_time=250.0)

    # Create tile 3 (300 bytes) -> total would be 900 > 700 -> must evict tile 2
    t3_path = cache_dir / "tile_3.json"
    t3_path.write_bytes(b"x" * 300)
    evicted = mgr.record_tile("tile_3", "2026-08-01", t3_path, access_time=300.0)

    assert evicted == ["tile_2"]
    assert mgr.get_total_bytes() <= 700
    assert mgr.get_total_bytes() == 600

    # Anti-vacuity assertions
    assert not t2_path.exists(), "tile_2 was LRU and must be deleted from disk"
    assert t1_path.exists(), "tile_1 was touched and must survive"
    assert t3_path.exists(), "tile_3 is newest and must survive"
    assert len(mgr.list_tiles()) == 2
