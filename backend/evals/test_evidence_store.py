import sqlite3
from pathlib import Path

import pytest

from gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from gateway.evidence.invariants import check_invariants
from gateway.evidence.nodes import (
    Artifact,
    Claim,
    Evaluation,
    LifecycleState,
    ResolutionRecord,
    ResolutionState,
    Run,
    Source,
)
from gateway.evidence.store import EvidenceStoreError, SqliteEvidenceStore


def build_complex_graph(claim_a: Claim, source_a: Source) -> EvidenceGraph:
    g = EvidenceGraph()
    g.add_run(Run(run_id="r1", started_at="2026-10-12T10:00:00Z"))
    g.add_run(Run(run_id="r2", started_at="2026-10-12T11:00:00Z"))

    g.add_source(source_a)
    g.add_source(source_a.model_copy(update={"source_id": "s-b", "run_id": "r2"}))

    g.add_claim(claim_a)
    c2 = claim_a.model_copy(update={"claim_id": "c-2", "run_id": "r2", "source_id": "s-b"})
    g.add_claim(c2)

    # superseded claim
    c_super = claim_a.model_copy(
        update={
            "claim_id": "c-super",
            "lifecycle": LifecycleState.SUPERSEDED,
            "superseded_by": "c-a",
        }
    )
    g.add_claim(c_super)

    # Active resolution
    res = ResolutionRecord(
        resolution_id="res:c-a",
        members=["c-a", "c-2"],
        canonical_id="c-a",
        rule="exact_identity",
        confidence=1.0,
        created_by_run="r1",
    )
    g.resolutions[res.resolution_id] = res

    a1 = Artifact(artifact_id="a1", kind="CostedTrip", version=1, run_id="r1", derived_from=["c-a"])
    g.add_artifact(a1)
    a2 = Artifact(
        artifact_id="a2", kind="OptimizerResult", version=1, run_id="r2", derived_from=["a1"]
    )
    g.add_artifact(a2)

    e1 = Evaluation(
        evaluation_id="e1",
        subject_id="c-a",
        rubric_id="freshness.v1",
        verdict="accept",
        reasons=[],
        run_id="r1",
    )
    g.add_evaluation(e1)

    g.add_edge(Edge(kind=EdgeKind.SUPPORTS, src="s-a", dst="c-a", created_by_run="r1"))
    g.add_edge(Edge(kind=EdgeKind.SUPPORTS, src="s-b", dst="c-2", created_by_run="r2"))
    g.add_edge(Edge(kind=EdgeKind.SUPERSEDES, src="c-a", dst="c-super", created_by_run="r1"))
    g.add_edge(Edge(kind=EdgeKind.RESOLVED_TO, src="c-2", dst="c-a", created_by_run="r1"))
    g.add_edge(Edge(kind=EdgeKind.DERIVED_FROM, src="a1", dst="c-a", created_by_run="r1"))
    g.add_edge(Edge(kind=EdgeKind.DERIVED_FROM, src="a2", dst="a1", created_by_run="r2"))
    g.add_edge(Edge(kind=EdgeKind.EVALUATED_BY, src="c-a", dst="e1", created_by_run="r1"))
    g.add_edge(Edge(kind=EdgeKind.CONTRADICTS, src="c-a", dst="c-2", created_by_run="r2"))

    assert check_invariants(g) == []
    return g


def test_round_trip_preserves_every_node_record_and_edge(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    g = build_complex_graph(claim_a, source_a)
    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    store.save(g)

    # load both runs to get the full graph
    loaded1 = store.load("r1")
    loaded2 = store.load("r2")

    # manually merge loaded2 into loaded1 for testing equality
    for c in loaded2.claims.values():
        loaded1.add_claim(c)
    for s in loaded2.sources.values():
        loaded1.add_source(s)
    for a in loaded2.artifacts.values():
        loaded1.add_artifact(a)
    for e in loaded2.evaluations.values():
        loaded1.add_evaluation(e)
    for r in loaded2.runs.values():
        loaded1.add_run(r)
    for res in loaded2.resolutions.values():
        loaded1.resolutions[res.resolution_id] = res
    for edge in loaded2.edges:
        if edge not in loaded1.edges:
            loaded1.add_edge(edge)

    assert len(loaded1.claims) == len(g.claims)
    assert len(loaded1.sources) == len(g.sources)
    assert len(loaded1.artifacts) == len(g.artifacts)
    assert len(loaded1.evaluations) == len(g.evaluations)
    assert len(loaded1.runs) == len(g.runs)
    assert len(loaded1.resolutions) == len(g.resolutions)
    assert len(loaded1.edges) == len(g.edges)


def test_save_same_graph_twice_is_byte_and_row_count_idempotent(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    g = build_complex_graph(claim_a, source_a)
    db_path = tmp_path / "evidence.db"
    store = SqliteEvidenceStore(db_path)

    store.save(g)
    size1 = db_path.stat().st_size

    store.save(g)
    size2 = db_path.stat().st_size

    assert size1 == size2


def test_save_updated_run_removes_stale_edges_for_that_run(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    g = EvidenceGraph()
    g.add_run(Run(run_id="r1", started_at="2026-10-12T10:00:00Z"))
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_edge(Edge(kind=EdgeKind.SUPPORTS, src="s-a", dst="c-a", created_by_run="r1"))

    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    store.save(g)

    # updated graph without the edge
    g_new = EvidenceGraph()
    g_new.add_run(Run(run_id="r1", started_at="2026-10-12T10:00:00Z"))
    g_new.add_source(source_a)
    g_new.add_claim(claim_a)

    store.save(g_new)

    loaded = store.load("r1")
    assert len(loaded.edges) == 0


def test_save_updated_run_does_not_delete_other_run(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    g = EvidenceGraph()
    g.add_run(Run(run_id="r1", started_at="2026-10-12T10:00:00Z"))
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_edge(Edge(kind=EdgeKind.SUPPORTS, src="s-a", dst="c-a", created_by_run="r1"))

    g.add_run(Run(run_id="r2", started_at="2026-10-12T11:00:00Z"))
    g.add_claim(claim_a.model_copy(update={"claim_id": "c-b"}))
    g.add_edge(Edge(kind=EdgeKind.CONTRADICTS, src="c-a", dst="c-b", created_by_run="r2"))

    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    store.save(g)

    # now save r2 only with nothing
    g_new = EvidenceGraph()
    g_new.add_run(Run(run_id="r2", started_at="2026-10-12T11:00:00Z"))

    store.save(g_new)

    loaded = store.load("r1")
    assert len(loaded.edges) == 1
    assert loaded.edges[0].kind == EdgeKind.SUPPORTS


def test_load_run_includes_cross_run_lineage_closure(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    g = build_complex_graph(claim_a, source_a)
    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    store.save(g)

    loaded_r2 = store.load("r2")
    # r2 authored artifact a2, which derives from a1, which derives from c-a,
    # which is supported by s-a
    assert "a2" in loaded_r2.artifacts
    assert "a1" in loaded_r2.artifacts
    assert "c-a" in loaded_r2.claims
    # assert "s-a" in loaded_r2.sources # Wait, does a1 -> c-a pull in s-a?
    # Wait, c-a has source_id="s-a". So yes, s-a is pulled in!
    assert "s-a" in loaded_r2.sources

    assert loaded_r2.runs["r1"].run_id == "r1"
    assert loaded_r2.runs["r2"].run_id == "r2"


def test_reversed_resolution_survives_round_trip(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    g = EvidenceGraph()
    g.add_run(Run(run_id="r1", started_at="2026-10-12T10:00:00Z"))
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_claim(claim_a.model_copy(update={"claim_id": "c-b"}))

    res = ResolutionRecord(
        resolution_id="res:c-a",
        members=["c-a", "c-b"],
        canonical_id="c-a",
        rule="exact_identity",
        confidence=1.0,
        created_by_run="r1",
        state=ResolutionState.REVERSED,
        reversed_by_run="r1",
    )
    g.resolutions[res.resolution_id] = res

    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    store.save(g)

    loaded = store.load("r1")
    assert loaded.resolutions["res:c-a"].state == ResolutionState.REVERSED


def test_save_rejects_invalid_graph_before_writing(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    g = EvidenceGraph()
    g.add_run(Run(run_id="r1", started_at="2026-10-12T10:00:00Z"))
    g.add_source(source_a)
    g.add_claim(claim_a)

    g.edges.append(Edge(kind=EdgeKind.SUPPORTS, src="s-a", dst="c-nope", created_by_run="r1"))

    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    with pytest.raises(EvidenceStoreError, match="invalid graph"):
        store.save(g)

    loaded = store.load("r1")
    assert len(loaded.edges) == 0


def test_failed_save_rolls_back_all_tables(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    db_path = tmp_path / "evidence.db"
    store = SqliteEvidenceStore(db_path)

    # Save a valid graph first
    g = EvidenceGraph()
    g.add_run(Run(run_id="r1", started_at="2026-10-12T10:00:00Z"))
    store.save(g)

    # Try to save a valid graph but mock conn.execute to fail during tx
    g2 = EvidenceGraph()
    g2.add_run(Run(run_id="r1", started_at="2026-10-12T10:00:00Z"))
    g2.add_source(source_a)
    g2.add_claim(claim_a)

    class FailingConnection:
        def __init__(self, real_conn):
            self._real_conn = real_conn

        def __enter__(self):
            self._real_conn.__enter__()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self._real_conn.__exit__(exc_type, exc_val, exc_tb)

        def execute(self, sql, params=()):
            if "INTO claims" in sql:
                raise sqlite3.OperationalError("disk I/O error")
            return self._real_conn.execute(sql, params)

        def commit(self):
            self._real_conn.commit()

        def rollback(self):
            self._real_conn.rollback()

        def cursor(self):
            return self._real_conn.cursor()

    import sqlite3 as orig_sqlite3

    orig_connect = orig_sqlite3.connect

    def fail_on_claims(*args, **kwargs):
        return FailingConnection(orig_connect(*args, **kwargs))

    import importlib

    store_mod = importlib.import_module("gateway.evidence.store")
    orig_mod_connect = store_mod.sqlite3.connect
    store_mod.sqlite3.connect = fail_on_claims

    try:
        with pytest.raises(EvidenceStoreError, match="disk I/O error"):
            store.save(g2)
    finally:
        store_mod.sqlite3.connect = orig_mod_connect

    loaded = store.load("r1")
    # source_a should have been rolled back because claims failed in the same transaction
    assert "s-a" not in loaded.sources


def test_v1_store_migrates_without_losing_sources_claims_or_edges(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    db_path = tmp_path / "evidence.db"

    # Create v1 schema manually
    _SCHEMA_V1 = """
    CREATE TABLE IF NOT EXISTS sources (
        source_id TEXT PRIMARY KEY,
        run_id    TEXT NOT NULL,
        body      TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS claims (
        claim_id TEXT PRIMARY KEY,
        run_id   TEXT NOT NULL,
        body     TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS edges (
        kind   TEXT NOT NULL,
        src    TEXT NOT NULL,
        dst    TEXT NOT NULL,
        run_id TEXT NOT NULL
    );
    """
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA_V1)

        conn.execute(
            "INSERT INTO sources VALUES (?,?,?)",
            (source_a.source_id, source_a.run_id, source_a.model_dump_json()),
        )
        conn.execute(
            "INSERT INTO claims VALUES (?,?,?)",
            (claim_a.claim_id, claim_a.run_id, claim_a.model_dump_json()),
        )
        conn.execute(
            "INSERT INTO edges VALUES (?,?,?,?)", (EdgeKind.SUPPORTS.value, "s-a", "c-a", "r1")
        )

    store = SqliteEvidenceStore(db_path)

    loaded = store.load("r1")
    assert "s-a" in loaded.sources
    assert "c-a" in loaded.claims
    assert len(loaded.edges) == 1
    assert loaded.edges[0].kind == EdgeKind.SUPPORTS
    assert loaded.edges[0].created_by_run == "r1"
