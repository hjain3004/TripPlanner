"""SQLite-backed evidence graph persistence.

Design §11.1 resolved in favour of edge tables in the existing relational store:
no new dependency, and cross-run lineage survives.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from gateway.evidence.nodes import Claim, Source

_SCHEMA = """
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
CREATE INDEX IF NOT EXISTS idx_claims_run ON claims(run_id);
CREATE INDEX IF NOT EXISTS idx_edges_run  ON edges(run_id);
"""


class SqliteEvidenceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with sqlite3.connect(self.path) as conn:
            conn.executescript(_SCHEMA)

    def _run_id_for(self, graph: EvidenceGraph, node_id: str) -> str:
        claim = graph.claims.get(node_id)
        if claim is not None:
            return claim.run_id
        for candidate in graph.claims.values():
            if candidate.source_id == node_id:
                return candidate.run_id
        return "r1"

    def save(self, graph: EvidenceGraph) -> None:
        with sqlite3.connect(self.path) as conn:
            for source in graph.sources.values():
                conn.execute(
                    "INSERT OR REPLACE INTO sources VALUES (?,?,?)",
                    (source.source_id,
                     self._run_id_for(graph, source.source_id),
                     source.model_dump_json()),
                )
            for claim in graph.claims.values():
                conn.execute(
                    "INSERT OR REPLACE INTO claims VALUES (?,?,?)",
                    (claim.claim_id, claim.run_id, claim.model_dump_json()),
                )
            for edge in graph.edges:
                conn.execute(
                    "INSERT INTO edges VALUES (?,?,?,?)",
                    (edge.kind.value, edge.src, edge.dst,
                     self._run_id_for(graph, edge.dst)),
                )

    def load(self, run_id: str) -> EvidenceGraph:
        graph = EvidenceGraph()
        with sqlite3.connect(self.path) as conn:
            for (body,) in conn.execute(
                "SELECT body FROM sources WHERE run_id = ?", (run_id,)
            ):
                graph.add_source(Source.model_validate_json(body))
            for (body,) in conn.execute(
                "SELECT body FROM claims WHERE run_id = ?", (run_id,)
            ):
                graph.add_claim(Claim.model_validate_json(body))
            for kind, src, dst in conn.execute(
                "SELECT kind, src, dst FROM edges WHERE run_id = ?", (run_id,)
            ):
                graph.add_edge(
                    Edge(kind=EdgeKind(kind), src=src, dst=dst, created_by_run=run_id)
                )
        return graph
