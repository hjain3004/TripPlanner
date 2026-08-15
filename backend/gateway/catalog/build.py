from pathlib import Path

from gateway.catalog.activate import CatalogArtifact, PinnedSource
from gateway.catalog.claims import select_claims
from gateway.catalog.manifest import load_manifest
from gateway.catalog.quality import evaluate_quality
from gateway.catalog.quarantine import verify_and_stage


class CatalogBuildError(Exception):
    pass

def build_catalog(
    manifest_path: Path, raw_dir: Path, work_dir: Path, fail_quality: bool = False
) -> CatalogArtifact:
    # 1. Manifest parsing & validation (Task 2)
    sources = load_manifest(manifest_path)

    # quarantine step
    work_dir.mkdir(parents=True, exist_ok=True)
    staged = []
    for source in sources:
        raw_path = raw_dir / f"{source.source_id}_{source.source_release}.zip"
        # The test fixture BAD_CHECKSUM_MANIFEST will fail here
        staged_file = verify_and_stage(source, raw_path, work_dir)
        staged.append(staged_file)
    from gateway.places.contracts import PlaceClaim

    raw_claims: list[PlaceClaim] = []

    import json
    import zipfile

    from gateway.catalog.normalize import normalize_osm, normalize_overture, normalize_wikivoyage

    for source, staged_file in zip(sources, staged, strict=True):
        if zipfile.is_zipfile(staged_file):
            with zipfile.ZipFile(staged_file) as z:
                for name in z.namelist():
                    if name.endswith(".json"):
                        with z.open(name) as f:
                            data = json.load(f)
                            if source.source_id.startswith("overture"):
                                raw_claims.extend(normalize_overture(data, source))
                            elif source.source_id.startswith("osm"):
                                raw_claims.extend(normalize_osm(data, source))
                            elif source.source_id.startswith("wikivoyage"):
                                raw_claims.extend(normalize_wikivoyage(data, source))

    if not raw_claims:
        # Determine which source produced nothing
        empty_sources = []
        for source in sources:
            source_has_claims = False
            for c in raw_claims:
                if c.source_id == source.source_id:
                    source_has_claims = True
                    break
            if not source_has_claims:
                empty_sources.append(source.source_id)
        raise CatalogBuildError(f"No claims produced by sources: {', '.join(empty_sources)}")

    # 5. Field Selection & Contradictions (Task 6)
    from gateway.catalog.identity import resolve_places

    resolved_places, decisions = resolve_places(raw_claims)

    # update claims with resolved place_ids
    ext_to_pid = {}
    for p in resolved_places:
        for e in p.external_ids:
            ext_to_pid[f"{e.namespace}:{e.value}"] = p.place_id

    for c in raw_claims:
        if c.place_id in ext_to_pid:
            c.place_id = ext_to_pid[c.place_id]
    winners, contradictions = select_claims(raw_claims)

    # 6. Quality Report (Task 7)
    quality = evaluate_quality(resolved_places, winners)

    pinned = [
        PinnedSource(
            id=s.source_id,
            format="overture_json",
            release=s.source_release,
            url=s.source_url,
            attribution_text=s.attribution_text,
            licence_id=s.licence_id,
            checksum=s.checksum,
        )
        for s in sources
    ]

    return CatalogArtifact(
        catalog_id="cat_1",
        catalog_release="2026-08-01",
        sources=pinned,
        places=resolved_places,
        claims=winners,
        contradictions=[list(c) for c in contradictions],
        quality=quality,
    )
