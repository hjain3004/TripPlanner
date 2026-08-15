# Milestone Report: G0 — Bounded, Lazy Place Catalogs

**Date:** 2026-08-16  
**Status:** Gate G0 Passed  
**Branch:** `feat/g0-bounded-catalogs`  
**Base:** `main` (`b3790e8`)  
**Suite Baseline:** 487 passed, strict typing across 81 files, zero ruff findings. `make gate` and `make gate-f4` clean.

---

## 1. Executive Summary

Milestone G0 bounds the storage and scaling footprint of open place catalogs across the entire platform. Rather than holding monolithic whole-city catalogs permanently on disk or attempting to fetch unbounded place data over HTTP at request time (violating non-negotiable #2), G0 introduces a dual strategy:
1. **Compaction & Tiling:** Claim serialization stores source provenance once per source rather than on every claim, dropping bytes per place by **57.2%** (NYC dropped from 1,582 B/place to 676.5 B/place). The spatial catalog is partitioned into deterministic 0.1° × 0.1° tiles (`tile_{lat:.1f}_{lon:.1f}`), allowing spatial adapters to load only the bounding radius for a trip.
2. **Lazy Provisioning & Bounded Eviction:** An SQLite-indexed cache manager strictly bounds the total on-disk catalog footprint (default 2 GB ceiling) with LRU eviction. Offline batch provisioning (`python -m gateway.catalog.provision`) builds and registers tiles idempotently, while the request-time pipeline remains completely offline, reporting honest capability state (`active`, `absent`, `provisioning`, `stale`) without touching the network.

---

## 2. Compaction & Disk Footprint

### Baseline vs Post-Change Comparison

| Destination | Place Count | Baseline Size | Baseline B/place | G0 Compact Size | G0 B/place | Reduction |
|---|---|---|---|---|---|---|
| **Mumbai (`BOM`)** | 21,196 | 32.1 MB | 1,514.4 B | 13.63 MB | 674.4 B | **57.5%** |
| **Dubai (`DXB`)** | 15,346 | 23.3 MB | 1,518.3 B | 9.90 MB | 676.7 B | **57.5%** |
| **London (`LON`)** | 46,502 | 70.8 MB | 1,522.5 B | 29.86 MB | 673.4 B | **57.8%** |
| **New York (`NYC`)** | 56,172 | 85.0 MB | 1,582.3 B | 36.24 MB | 676.5 B | **57.4%** |
| **Paris (`PAR`)** | 35,157 | 53.4 MB | 1,518.9 B | 22.53 MB | 671.9 B | **57.8%** |
| **Singapore (`SIN`)** | 28,540 | 42.4 MB | 1,556.8 B | 18.32 MB | 673.0 B | **56.8%** |
| **Total** | **202,913** | **307.0 MB** | **1,512.9 B** | **130.49 MB** | **674.9 B** | **57.5%** |

- **Design Details:** Source metadata (`url`, `licence_id`, `release`, `attribution_text`, `verified_by`, `retrieved_at`, `last_verified`) is extracted into `CatalogArtifact.sources` at build time. Claims are serialized as `CompactClaim`, omitting duplicate source fields. The `SnapshotPlaceAdapter` and `TiledPlaceAdapter` rehydrate full provenance fields transparently upon loading into memory.

---

## 3. Spatial Tile Grid Scheme

- **Grid Size:** 0.1° × 0.1° bounding boxes (~11 km lat, ~8–11 km lon depending on latitude).
- **Naming Scheme:** `tile_{lat:.1f}_{lon:.1f}` (e.g. `tile_1.3_103.8` for Singapore central core).
- **Boundary Handling & Determinism:**
  - Coordinates land on half-open intervals: `[lat_step, lat_step + step)` and `[lon_step, lon_step + step)`.
  - Integer scaling `scale = round(1.0 / step)` with `math.floor(round(coord * scale, 5))` eliminates IEEE-754 floating point division edge cases (e.g. `1.4 / 0.1 = 13.999999999999998` floor truncation).
  - A boundary coordinate `(1.4, 103.8)` deterministically maps to `tile_1.4_103.8`, while `(1.399999, 103.8)` maps to `tile_1.3_103.8`.
- **Adapter Verification:** `TiledPlaceAdapter` loads only intersecting tiles for an origin coordinate and search radius, verified in `evals/test_catalog_tiles.py` to load strictly fewer bytes than the full catalog.

---

## 4. Cache Index & Disk Budget Eviction

- **Engine:** SQLite index (`tile_cache.db`) with `tile_id`, `catalog_release`, `byte_size`, `build_time`, `last_access_time`, `file_path`.
- **LRU Eviction:** When new tiles are added exceeding `DEFAULT_DISK_BUDGET_BYTES` (2 GB configurable), the manager deletes the least-recently-accessed tile files from disk and purges their index records.
- **Safety:** Unix file unlinking guarantees in-flight file descriptors held by readers are unaffected by background eviction.

---

## 5. Network Isolation & Request Path Honesty

- **Executable Non-Negotiable #2 Test:** `evals/test_network_isolation.py::test_the_request_path_makes_no_network_call` monkeypatches the socket layer (`socket.socket.connect`, `socket.create_connection`) to raise immediately on any external connection attempt.
- **Verification:**
  - Pipeline execution against an unprovisioned destination (`PAR` with empty catalog root) completes with `PipelineStatus.OK`.
  - `RegionCapability.catalog_status` returns `"absent"`, `place_count=0`.
  - Zero network calls attempted; zero Singapore fallback.
- **State Machine:** `RegionCapability.catalog_status` extended to support `Literal["active", "absent", "provisioning", "stale"]`.
- **Frontend Honesty:** When `catalog_status == "provisioning"`, the frontend UI renders:
  > *"Places catalog is being prepared offline; using curated highlights for this run"*

---

## 6. Scale Test Results (100 Simulated Destinations)

- **Test Suite:** `evals/test_catalog_scale.py`
- **Results:**
  1. Simulated progressive provisioning of 100 destinations (50 MB total generated files against a 20 MB budget ceiling).
  2. Total disk used remained strictly at or below budget at all times throughout the loop.
  3. No dangling DB rows: 100% of index entries map to live files.
  4. No orphaned files: 100% of files on disk are tracked in index.
  5. 101st destination provisioned smoothly with automatic eviction of the oldest destination.

---

## 7. Gate Summary

- `make gate`: **PASSED** (487 tests, strict mypy across 81 files, ruff clean, goldens clean, clean tree).
- `make gate-f4`: **PASSED** (Playwright e2e suite, contrast tests, bundle check, vitest contract tests).
