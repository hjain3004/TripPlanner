"""SQLite-backed evidence graph persistence.

Design §11.1 resolved in favour of edge tables in the existing relational store:
no new dependency, and cross-run lineage survives.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from gateway.evidence.invariants import check_invariants
from gateway.evidence.nodes import (
    Artifact,
    Claim,
    Evaluation,
    ResolutionRecord,
    Run,
    Source,
)

_SCHEMA_V2 = """
PRAGMA foreign_keys = ON;
PRAGMA user_version = 2;

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resolutions (
    id TEXT PRIMARY KEY, created_by_run TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
    kind TEXT NOT NULL,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    created_by_run TEXT NOT NULL,
    PRIMARY KEY (kind, src, dst, created_by_run)
);

CREATE INDEX IF NOT EXISTS idx_sources_run ON sources(run_id);
CREATE INDEX IF NOT EXISTS idx_claims_run ON claims(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_run ON evaluations(run_id);
CREATE INDEX IF NOT EXISTS idx_resolutions_run ON resolutions(created_by_run);
CREATE INDEX IF NOT EXISTS idx_edges_run ON edges(created_by_run);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
"""


class EvidenceStoreError(Exception):
    def __init__(self, message: str, violations: list[str] | None = None) -> None:
        super().__init__(message)
        self.violations = violations or []


class SqliteEvidenceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.path) as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA user_version")
            row = cur.fetchone()
            version = row[0] if row else 0

            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='edges'")
            has_edges = cur.fetchone() is not None
            is_v1 = False
            if has_edges:
                cur.execute("PRAGMA table_info(edges)")
                columns = {r[1] for r in cur.fetchall()}
                is_v1 = "run_id" in columns and "created_by_run" not in columns

            if not has_edges and version == 0:
                conn.executescript(_SCHEMA_V2)
            elif is_v1 or version == 1:
                self._migrate_v1_to_v2(conn)
            elif version > 2:
                raise EvidenceStoreError(f"unsupported schema version {version}")

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.cursor()

            cur.execute("ALTER TABLE sources RENAME TO v1_sources")
            cur.execute("ALTER TABLE claims RENAME TO v1_claims")
            cur.execute("ALTER TABLE edges RENAME TO v1_edges")

            for stmt in _SCHEMA_V2.split(";"):
                stmt = stmt.strip()
                if not stmt or stmt.startswith("PRAGMA"):
                    continue
                cur.execute(stmt)

            cur.execute("SELECT source_id, body FROM v1_sources")
            sources = cur.fetchall()

            cur.execute("SELECT claim_id, run_id, body FROM v1_claims")
            claims = cur.fetchall()

            claim_runs: dict[str, str] = {row[0]: row[1] for row in claims}
            source_runs: dict[str, set[str]] = {}
            for row in claims:
                body = json.loads(row[2])
                s_id = body.get("source_id")
                if s_id:
                    source_runs.setdefault(s_id, set()).add(row[1])

            for source_id, s_body in sources:
                s_runs = source_runs.get(source_id, set())
                if len(s_runs) != 1:
                    raise EvidenceStoreError(
                        f"Cannot uniquely derive run ownership for source {source_id}"
                    )
                run_id = list(s_runs)[0]
                cur.execute(
                    "INSERT INTO sources (id, run_id, body) VALUES (?, ?, ?)",
                    (source_id, run_id, s_body),
                )

            for claim_id, c_run_id, c_body in claims:
                cur.execute(
                    "INSERT INTO claims (id, run_id, body) VALUES (?, ?, ?)",
                    (claim_id, c_run_id, c_body),
                )

            cur.execute("SELECT kind, src, dst FROM v1_edges")
            edges = cur.fetchall()
            for kind, src, dst in edges:
                e_run_id = claim_runs.get(dst)
                if not e_run_id:
                    e_run_id = claim_runs.get(src)
                if not e_run_id:
                    raise EvidenceStoreError(
                        f"Cannot uniquely derive run ownership for edge {src}->{dst}"
                    )
                cur.execute(
                    "INSERT INTO edges (kind, src, dst, created_by_run) VALUES (?, ?, ?, ?)",
                    (kind, src, dst, e_run_id),
                )

            cur.execute("DROP TABLE v1_sources")
            cur.execute("DROP TABLE v1_claims")
            cur.execute("DROP TABLE v1_edges")

            cur.execute("PRAGMA user_version = 2")
            conn.commit()
        except Exception as e:
            conn.rollback()
            if isinstance(e, EvidenceStoreError):
                raise
            raise EvidenceStoreError(f"Migration failed: {e}") from e

    def save(self, graph: EvidenceGraph) -> None:
        violations = check_invariants(graph)
        if violations:
            raise EvidenceStoreError("cannot save invalid graph", violations)

        touched_runs: set[str] = set()
        for node in (
            list(graph.claims.values())
            + list(graph.artifacts.values())
            + list(graph.evaluations.values())
        ):
            touched_runs.add(node.run_id)
        for res in graph.resolutions.values():
            touched_runs.add(res.created_by_run)
        for edge in graph.edges:
            touched_runs.add(edge.created_by_run)

        for source in graph.sources.values():
            if hasattr(source, "run_id") and source.run_id:
                touched_runs.add(source.run_id)

        for run in graph.runs.values():
            touched_runs.add(run.run_id)

        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            try:
                for source in graph.sources.values():
                    conn.execute(
                        "INSERT OR REPLACE INTO sources (id, run_id, body) VALUES (?,?,?)",
                        (source.source_id, source.run_id, source.model_dump_json()),
                    )
                for claim in graph.claims.values():
                    conn.execute(
                        "INSERT OR REPLACE INTO claims (id, run_id, body) VALUES (?,?,?)",
                        (claim.claim_id, claim.run_id, claim.model_dump_json()),
                    )
                for artifact in graph.artifacts.values():
                    conn.execute(
                        "INSERT OR REPLACE INTO artifacts (id, run_id, body) VALUES (?,?,?)",
                        (artifact.artifact_id, artifact.run_id, artifact.model_dump_json()),
                    )
                for run in graph.runs.values():
                    conn.execute(
                        "INSERT OR REPLACE INTO runs (id, body) VALUES (?,?)",
                        (run.run_id, run.model_dump_json()),
                    )
                for evaluation in graph.evaluations.values():
                    conn.execute(
                        "INSERT OR REPLACE INTO evaluations (id, run_id, body) VALUES (?,?,?)",
                        (evaluation.evaluation_id, evaluation.run_id, evaluation.model_dump_json()),
                    )


                sync_runs = touched_runs if graph.authoritative_runs is None else graph.authoritative_runs
                if sync_runs:
                    run_list = ",".join("?" for _ in sync_runs)
                    params = tuple(sync_runs)

                    conn.execute(f"DELETE FROM edges WHERE created_by_run IN ({run_list})", params)
                    conn.execute(f"DELETE FROM resolutions WHERE created_by_run IN ({run_list})", params)

                for edge in graph.edges:
                    if edge.created_by_run in touched_runs:
                        conn.execute(
                            "INSERT OR REPLACE INTO edges (kind, src, dst, created_by_run) "
                            "VALUES (?,?,?,?)",
                            (edge.kind.value, edge.src, edge.dst, edge.created_by_run),
                        )

                for res in graph.resolutions.values():
                    if res.created_by_run in touched_runs:
                        conn.execute(
                            "INSERT OR REPLACE INTO resolutions (id, created_by_run, body) VALUES (?,?,?)",
                            (res.resolution_id, res.created_by_run, res.model_dump_json()),
                        )
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise EvidenceStoreError(f"Save failed: {e}") from e

    def load(self, run_id: str) -> EvidenceGraph:
        graph = EvidenceGraph(authoritative_runs={run_id})
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")

            cur = conn.cursor()

            loaded_edges: list[tuple[str, str, str, str]] = []
            cur.execute(
                "SELECT kind, src, dst, created_by_run FROM edges WHERE created_by_run = ?",
                (run_id,),
            )
            loaded_edges.extend(cur.fetchall())

            nodes: dict[str, set[str]] = {
                "sources": set(),
                "claims": set(),
                "artifacts": set(),
                "runs": set(),
                "evaluations": set(),
                "resolutions": set(),
            }

            cur.execute("SELECT id FROM sources WHERE run_id = ?", (run_id,))
            nodes["sources"].update(row[0] for row in cur.fetchall())

            cur.execute("SELECT id FROM claims WHERE run_id = ?", (run_id,))
            nodes["claims"].update(row[0] for row in cur.fetchall())

            cur.execute("SELECT id FROM artifacts WHERE run_id = ?", (run_id,))
            nodes["artifacts"].update(row[0] for row in cur.fetchall())

            nodes["runs"].add(run_id)

            cur.execute("SELECT id FROM evaluations WHERE run_id = ?", (run_id,))
            nodes["evaluations"].update(row[0] for row in cur.fetchall())

            cur.execute("SELECT id FROM resolutions WHERE created_by_run = ?", (run_id,))
            nodes["resolutions"].update(row[0] for row in cur.fetchall())

            bodies: dict[str, dict[str, str]] = {
                "sources": {},
                "claims": {},
                "artifacts": {},
                "runs": {},
                "evaluations": {},
                "resolutions": {},
            }

            def load_bodies(table: str, id_set: set[str]) -> None:
                missing = id_set - set(bodies[table].keys())
                if missing:
                    q = ",".join("?" for _ in missing)
                    cur.execute(f"SELECT id, body FROM {table} WHERE id IN ({q})", tuple(missing))
                    for rid, body in cur.fetchall():
                        bodies[table][rid] = body

            while True:
                prev_counts = sum(len(b) for b in bodies.values()) + len(loaded_edges)

                for table, id_set in nodes.items():
                    load_bodies(table, id_set)

                import json

                unknown_ids = set()

                for claim_body in bodies["claims"].values():
                    data = json.loads(claim_body)
                    if data.get("source_id"):
                        nodes["sources"].add(data["source_id"])
                    if data.get("run_id"):
                        nodes["runs"].add(data["run_id"])
                    if data.get("superseded_by"):
                        nodes["claims"].add(data["superseded_by"])

                for art_body in bodies["artifacts"].values():
                    data = json.loads(art_body)
                    if data.get("run_id"):
                        nodes["runs"].add(data["run_id"])
                    for did in data.get("derived_from", []):
                        unknown_ids.add(did)

                for eval_body in bodies["evaluations"].values():
                    data = json.loads(eval_body)
                    if data.get("run_id"):
                        nodes["runs"].add(data["run_id"])
                    if data.get("subject_id"):
                        unknown_ids.add(data["subject_id"])

                for res_body in bodies["resolutions"].values():
                    data = json.loads(res_body)
                    if data.get("created_by_run"):
                        nodes["runs"].add(data["created_by_run"])
                    if data.get("reversed_by_run"):
                        nodes["runs"].add(data["reversed_by_run"])
                    if data.get("canonical_id"):
                        nodes["claims"].add(data["canonical_id"])
                    for member in data.get("members", []):
                        nodes["claims"].add(member)

                for s_body in bodies["sources"].values():
                    data = json.loads(s_body)
                    if data.get("run_id"):
                        nodes["runs"].add(data["run_id"])

                for _r_body in bodies["runs"].values():
                    pass

                required_edge_srcs = set()
                required_edge_dsts = set()

                for claim_body in bodies["claims"].values():
                    data = json.loads(claim_body)
                    if data.get("source_id"):
                        required_edge_srcs.add(data["source_id"])
                        required_edge_dsts.add(data.get("claim_id"))
                    if data.get("superseded_by"):
                        required_edge_srcs.add(data["superseded_by"])
                        required_edge_dsts.add(data.get("claim_id"))

                for art_body in bodies["artifacts"].values():
                    data = json.loads(art_body)
                    art_id = data.get("artifact_id")
                    for did in data.get("derived_from", []):
                        required_edge_srcs.add(did)
                        required_edge_dsts.add(art_id)

                for eval_body in bodies["evaluations"].values():
                    data = json.loads(eval_body)
                    if data.get("subject_id"):
                        required_edge_srcs.add(data["subject_id"])
                        required_edge_dsts.add(data.get("evaluation_id"))

                for res_body in bodies["resolutions"].values():
                    data = json.loads(res_body)
                    res_id = data.get("resolution_id")
                    for member in data.get("members", []):
                        required_edge_srcs.add(member)
                        required_edge_dsts.add(res_id)

                if required_edge_srcs:
                    q = ",".join("?" for _ in required_edge_srcs)
                    cur.execute(
                        f"SELECT kind, src, dst, created_by_run FROM edges WHERE src IN ({q})",
                        tuple(required_edge_srcs),
                    )
                    for row in cur.fetchall():
                        if row not in loaded_edges and row[2] in required_edge_dsts:
                            loaded_edges.append(row)
                if required_edge_dsts:
                    q = ",".join("?" for _ in required_edge_dsts)
                    cur.execute(
                        f"SELECT kind, src, dst, created_by_run FROM edges WHERE dst IN ({q})",
                        tuple(required_edge_dsts),
                    )
                    for row in cur.fetchall():
                        if row not in loaded_edges and row[1] in required_edge_srcs:
                            loaded_edges.append(row)

                for e in loaded_edges:
                    nodes["runs"].add(e[3])
                    unknown_ids.add(e[1])
                    unknown_ids.add(e[2])

                known_ids = set()
                for table in ["sources", "claims", "artifacts", "evaluations", "resolutions"]:
                    known_ids.update(nodes[table])
                    known_ids.update(bodies[table].keys())
                
                unknown_ids -= known_ids
                if unknown_ids:
                    for table in ["sources", "claims", "artifacts", "evaluations", "resolutions"]:
                        if not unknown_ids:
                            break
                        found = set()
                        for chunk in [list(unknown_ids)[i:i+900] for i in range(0, len(unknown_ids), 900)]:
                            q = ",".join("?" for _ in chunk)
                            cur.execute(f"SELECT id FROM {table} WHERE id IN ({q})", tuple(chunk))
                            found.update(row[0] for row in cur.fetchall())
                        nodes[table].update(found)
                        unknown_ids -= found

                new_counts = sum(len(b) for b in bodies.values()) + len(loaded_edges)
                if new_counts == prev_counts:
                    break

        for b in bodies["sources"].values():
            graph.add_source(Source.model_validate_json(b))
        for b in bodies["claims"].values():
            graph.add_claim(Claim.model_validate_json(b))
        for b in bodies["artifacts"].values():
            graph.add_artifact(Artifact.model_validate_json(b))
        for b in bodies["runs"].values():
            graph.add_run(Run.model_validate_json(b))
        for b in bodies["evaluations"].values():
            graph.add_evaluation(Evaluation.model_validate_json(b))
        for b in bodies["resolutions"].values():
            graph.resolutions[ResolutionRecord.model_validate_json(b).resolution_id] = (
                ResolutionRecord.model_validate_json(b)
            )

        for kind, src, dst, c_run in loaded_edges:
            graph.add_edge(Edge(kind=EdgeKind(kind), src=src, dst=dst, created_by_run=c_run))

        violations = check_invariants(graph)
        if violations:
            raise EvidenceStoreError("loaded invalid graph", violations)

        return graph
