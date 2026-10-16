from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, Field

from ingestion.contracts import DiscoveryCandidate, PageKind, WatchTarget


class CuratorPromotion(BaseModel):
    curator_id: str = Field(min_length=1)
    decided_at: AwareDatetime
    source_policy_id: str = Field(min_length=1)


def promote_candidate_to_watch_target(
    candidate: DiscoveryCandidate, decision: CuratorPromotion
) -> WatchTarget:
    """Promote only the curator-selected issuer URL into the watchlist.

    Aggregator URL, source, claims, and guessed product values intentionally do
    not appear in the returned object. This is the structural trust boundary
    between discovery leads and financial evidence acquisition.
    """
    if candidate.status != "pending":
        raise ValueError("only pending discovery candidates can be promoted")
    if candidate.issuer_url_to_verify is None:
        raise ValueError("promotion requires an issuer URL selected by a curator")
    page_kind = {
        "card": PageKind.CARD_PAGE,
        "offer": PageKind.OFFER_PAGE,
        "welcome_bonus": PageKind.OFFER_PAGE,
    }[candidate.kind]
    return WatchTarget(
        target_id=f"watch:{candidate.id}",
        canonical_url=candidate.issuer_url_to_verify,
        source_policy_id=decision.source_policy_id,
        target_fact_ids=(f"candidate:{candidate.id}",),
        page_kind=page_kind,
        check_frequency_days=90 if candidate.kind != "card" else 365,
        preferred_backend="manual",
        manual_only=True,
        promoted_from_candidate_id=candidate.id,
        promoted_by=decision.curator_id,
        promoted_at=decision.decided_at,
    )
