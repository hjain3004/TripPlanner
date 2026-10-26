"""Evidence-span verification and financial-draft graph construction."""

from __future__ import annotations

import io
from datetime import UTC

from gateway.evidence.edges import EvidenceGraph
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import EvidenceSpan, SnapshotBundle


class EvidenceVerificationError(ValueError):
    pass


def verify_evidence_span(
    span: EvidenceSpan, *, snapshot: SnapshotBundle, artifacts: ContentAddressedStore
) -> None:
    try:
        normalized_bytes = artifacts.read(snapshot.normalized_artifact)
        raw_bytes = artifacts.read(snapshot.raw_artifact)
    except Exception as error:
        raise EvidenceVerificationError(
            "snapshot artifacts failed integrity verification"
        ) from error
    if normalized_bytes != snapshot.canonical_markdown.encode("utf-8"):
        raise EvidenceVerificationError("normalized artifact does not match snapshot text")
    if snapshot.normalized_sha256 != snapshot.normalized_artifact.sha256:
        raise EvidenceVerificationError("snapshot normalized hash is inconsistent")
    if snapshot.raw_sha256 != snapshot.raw_artifact.sha256 or not raw_bytes:
        raise EvidenceVerificationError("snapshot raw artifact is inconsistent")
    is_pdf_snapshot = snapshot.raw_artifact.media_type.split(";", 1)[0].lower() == "application/pdf"
    if is_pdf_snapshot and span.artifact_kind != "pdf":
        raise EvidenceVerificationError("PDF snapshots require PDF evidence spans")
    if not is_pdf_snapshot and span.artifact_kind == "pdf":
        raise EvidenceVerificationError("non-PDF snapshots cannot use PDF evidence spans")
    if span.snapshot_id != snapshot.snapshot_id:
        raise EvidenceVerificationError("evidence refers to another snapshot")
    if span.snapshot_hash != snapshot.normalized_sha256:
        raise EvidenceVerificationError("evidence hash does not match the immutable snapshot")
    if span.verification != "exact":
        raise EvidenceVerificationError("extractor verification flags are not trusted")
    actual = snapshot.canonical_markdown[span.normalized_start : span.normalized_end]
    if actual != span.quote:
        raise EvidenceVerificationError("evidence offsets do not select the quoted text")
    if not span.quote or span.quote not in snapshot.canonical_markdown:
        raise EvidenceVerificationError("evidence quote is absent from the snapshot")
    if span.artifact_kind == "pdf":
        if span.page_number is None:
            raise EvidenceVerificationError("PDF evidence requires a page")
        try:
            pdfplumber = __import__("pdfplumber")
            data = artifacts.read(snapshot.raw_artifact)
            with pdfplumber.open(io.BytesIO(data)) as document:
                if span.page_number > len(document.pages):
                    raise EvidenceVerificationError("PDF evidence page is outside the artifact")
                page_text = document.pages[span.page_number - 1].extract_text() or ""
                if span.quote not in page_text:
                    raise EvidenceVerificationError("PDF quote is not present on the cited page")
        except EvidenceVerificationError:
            raise
        except Exception as error:
            raise EvidenceVerificationError("PDF evidence could not be verified") from error
    elif span.page_number is not None:
        raise EvidenceVerificationError("non-PDF evidence cannot cite a page")


def financial_draft_graph(
    *, run_id: str, snapshot: SnapshotBundle, fields: list[str]
) -> EvidenceGraph:
    """Return the shared evidence graph representation for draft fields.

    The graph intentionally marks every claim ``VERIFY_REQUIRED``.  It is a
    lineage view, never an approval or financial-truth resolver.
    """
    from gateway.evidence.edges import Edge, EdgeKind
    from gateway.evidence.identity import ReferenceFactIdentity
    from gateway.evidence.nodes import (
        Artifact,
        Claim,
        ClaimKind,
        FreshnessState,
        Run,
        Source,
    )

    # Snapshot capture time is the stable run time for an immutable replay.
    now = snapshot.captured_at.astimezone(UTC)
    graph = EvidenceGraph()
    graph.add_run(Run(run_id=run_id, started_at=now, ended_at=now))
    source_id = f"financial-source:{snapshot.snapshot_id}"
    raw_artifact_id = f"financial-raw:{snapshot.raw_sha256}"
    normalized_artifact_id = f"financial-normalized:{snapshot.normalized_sha256}"
    artifact_id = f"financial-draft:{snapshot.snapshot_id}"
    graph.add_source(
        Source(
            source_id=source_id,
            run_id=run_id,
            provider="financial-ingestion",
            adapter_id="fi2-extractor",
            retrieved_at=snapshot.captured_at,
            source_url=f"snapshot:{snapshot.snapshot_id}",
        )
    )
    graph.add_artifact(
        Artifact(
            artifact_id=raw_artifact_id,
            kind="financial_raw_snapshot",
            run_id=run_id,
            version=1,
        )
    )
    graph.add_artifact(
        Artifact(
            artifact_id=normalized_artifact_id,
            kind="financial_normalized_snapshot",
            run_id=run_id,
            version=1,
        )
    )
    graph.add_artifact(
        Artifact(
            artifact_id=artifact_id,
            kind="financial_draft_snapshot",
            run_id=run_id,
            version=1,
            derived_from=[raw_artifact_id, normalized_artifact_id],
        )
    )
    for parent_id in (raw_artifact_id, normalized_artifact_id):
        graph.add_edge(
            Edge(
                kind=EdgeKind.DERIVED_FROM,
                src=artifact_id,
                dst=parent_id,
                created_by_run=run_id,
            )
        )
    for field in fields:
        claim_id = f"financial-draft:{snapshot.snapshot_id}:{field}"
        graph.add_claim(
            Claim(
                claim_id=claim_id,
                run_id=run_id,
                adapter_id="fi2-extractor",
                kind=ClaimKind.REFERENCE_FACT,
                identity=ReferenceFactIdentity(
                    kind="reference_fact",
                    namespace="financial_draft", entity_id=snapshot.target_id, field=field
                ),
                payload={"snapshot_id": snapshot.snapshot_id, "field_path": field},
                source_id=source_id,
                is_inference=False,
                status=FreshnessState.VERIFY_REQUIRED,
                needs_verification=True,
                confidence=0.0,
            )
        )
        graph.add_edge(
            Edge(
                kind=EdgeKind.SUPPORTS,
                src=source_id,
                dst=claim_id,
                created_by_run=run_id,
            )
        )
    return graph
