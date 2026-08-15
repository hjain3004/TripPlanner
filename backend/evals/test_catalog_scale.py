from pathlib import Path

from gateway.catalog.cache import TileCacheManager


def test_simulated_100_destinations_bounded_disk_and_integrity(tmp_path: Path) -> None:
    cache_dir = tmp_path / "tiles"
    cache_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "scale_cache.db"

    # Set a strict budget (e.g., 20 MB budget for fast test execution)
    budget_bytes = 20 * 1024 * 1024
    mgr = TileCacheManager(cache_dir=cache_dir, max_bytes=budget_bytes, db_path=db_path)

    # 100 simulated destinations, each generating 500 KB tile file (50 MB total > 20 MB budget)
    payload_size = 500 * 1024
    payload = b"0" * payload_size

    for i in range(1, 101):
        tile_id = f"tile_sim_{i:03d}"
        tile_path = cache_dir / f"{tile_id}.json"
        tile_path.write_bytes(payload)

        # Simulate progressive build time / access time
        mgr.record_tile(
            tile_id=tile_id,
            catalog_release="2026-08-01",
            file_path=tile_path,
            byte_size=payload_size,
            access_time=float(i * 10),
        )

        # Assertion 1: Total disk used never exceeds budget at any point
        actual_disk_bytes = sum(
            p.stat().st_size for p in cache_dir.glob("*.json")
        )
        assert actual_disk_bytes <= budget_bytes, (
            f"Disk budget exceeded on destination {i}: {actual_disk_bytes} > {budget_bytes}"
        )
        assert mgr.get_total_bytes() <= budget_bytes
        assert mgr.get_total_bytes() == actual_disk_bytes

    # Assertion 2: Index accurately reflects what is on disk (no dangling rows, no orphaned files)
    tracked_tiles = mgr.list_tiles()
    tracked_paths = {Path(t["file_path"]) for t in tracked_tiles}
    disk_paths = set(cache_dir.glob("*.json"))

    assert tracked_paths == disk_paths, "Mismatch between DB rows and files on disk"
    for p in tracked_paths:
        assert p.exists(), f"Dangling DB row for non-existent file {p}"

    # Anti-vacuity: verify that old destinations were evicted and recent ones survived
    surviving_ids = {t["tile_id"] for t in tracked_tiles}
    assert len(surviving_ids) == budget_bytes // payload_size
    assert "tile_sim_001" not in surviving_ids, "Oldest destination should be evicted"
    assert "tile_sim_100" in surviving_ids, "Newest destination should survive"

    # Assertion 3: Provisioning a 101st destination succeeds smoothly, evicting oldest
    tile_101 = cache_dir / "tile_sim_101.json"
    tile_101.write_bytes(payload)
    evicted = mgr.record_tile(
        tile_id="tile_sim_101",
        catalog_release="2026-08-01",
        file_path=tile_101,
        byte_size=payload_size,
        access_time=1010.0,
    )
    assert len(evicted) >= 1
    assert tile_101.exists()
    assert mgr.get_total_bytes() <= budget_bytes
    assert sum(p.stat().st_size for p in cache_dir.glob("*.json")) <= budget_bytes
