"""Deterministic word-boundary hotel property name -> loyalty chain matcher."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from core.loyalty.contracts import HotelBrandMatch, HotelChainBrandRule

# Aliases that represent generic English hospitality nouns on their own and therefore
# require either a multi-word chain suffix/qualifier or explicit contextual matching.
_AMBIGUOUS_SINGLE_WORD_ALIASES: frozenset[str] = frozenset(
    {
        "grand",
        "park",
        "crown",
        "royal",
        "palace",
        "view",
        "inn",
        "suites",
        "hotel",
        "resort",
        "edition",
        "caption",
        "canopy",
        "curio",
        "tapestry",
        "tempo",
        "tru",
        "even",
        "regent",
        "w",
        "lxr",
        "taj",
        "itc",
        "choice",
        "raffles",
    }
)

_W_BLOCKED_SECOND_TOKENS: frozenset[str] = frozenset(
    {
        "xyz",
        "hostel",
        "motel",
        "inn",
        "guesthouse",
        "guest",
        "lodge",
        "view",
        "suites",
        "apartments",
        "apartment",
        "street",
        "st",
        "road",
        "rd",
        "ave",
        "avenue",
        "block",
    }
)

_TAJ_BLOCKED_SECOND_TOKENS: frozenset[str] = frozenset(
    {
        "view",
        "guesthouse",
        "guest",
        "hostel",
        "inn",
        "lodge",
        "bazaar",
        "restaurant",
        "cafe",
        "homestay",
        "residency",
    }
)

_EDITION_CITY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "singapore",
        "london",
        "tokyo",
        "new york",
        "times square",
        "miami beach",
        "west hollywood",
        "tampa",
        "barcelona",
        "madrid",
        "rome",
        "milan",
        "reykjavik",
        "bodrum",
        "sanya",
        "shanghai",
        "abu dhabi",
        "dubai",
        "riviera maya",
        "doha",
        "jeddah",
        "como",
    }
)

_EDITION_EXCLUDE_PREV: frozenset[str] = frozenset(
    {"limited", "special", "first", "second", "new", "classic", "modern", "grand"}
)


def normalize_property_name(name: str) -> str:
    """Fold Unicode diacritics, collapse punctuation to single ASCII spaces, and casefold."""
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    ascii_chars = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-z0-9]+", " ", ascii_chars)
    return re.sub(r"\s+", " ", cleaned).strip()


def _match_contextual_brand(
    normalized_name: str, tokens: list[str], chain_id: str
) -> tuple[int, str, float] | None:
    """Handle inherently short or context-dependent hospitality brands safely.

    Returns ``(effective_word_rank, brand_label, confidence)``.
    """
    if not tokens:
        return None
    if chain_id == "marriott_bonvoy":
        # Match authentic W Hotels properties such as "W Singapore - Sentosa Cove" or "W Goa"
        # without ever matching "WXYZ Hostel" or "Hotel A to W".
        if len(tokens) >= 2 and tokens[0] == "w":
            second = tokens[1]
            if second in {"hotel", "hotels", "residences"}:
                return 2, "W Hotels", 0.92
            if second not in _W_BLOCKED_SECOND_TOKENS and len(second) >= 3:
                return 2, f"W {second.title()}", 0.78
        for idx in range(1, len(tokens)):
            if tokens[idx] != "edition":
                continue
            prev = tokens[idx - 1]
            prev_two = f"{tokens[idx - 2]} {tokens[idx - 1]}" if idx >= 2 else ""
            if prev not in _EDITION_EXCLUDE_PREV and (
                prev in _EDITION_CITY_ALLOWLIST or prev_two in _EDITION_CITY_ALLOWLIST
            ):
                return 2, "EDITION", 0.90
        if len(tokens) >= 2 and tokens[0] == "renaissance":
            if tokens[1] not in _W_BLOCKED_SECOND_TOKENS and (
                "hotel" in tokens or "resort" in tokens or "marriott" in tokens
            ):
                return 2, "Renaissance Hotel", 0.82
    if chain_id == "accor_all" and len(tokens) >= 2 and tokens[0] == "raffles":
        raffles_blocked = _W_BLOCKED_SECOND_TOKENS | {"place", "city", "quay", "mrt", "station"}
        if tokens[1] not in raffles_blocked and not (set(tokens[1:]) & {"hostel", "guesthouse"}):
            return 2, "Raffles", 0.88
    if chain_id == "taj_innercircle":
        if not (set(tokens) & _TAJ_BLOCKED_SECOND_TOKENS):
            if len(tokens) >= 2 and tokens[0] == "taj":
                return 2, "Taj Hotels", 0.80
            if len(tokens) >= 3 and tokens[0] == "the" and tokens[1] == "taj":
                return 2, "Taj Hotels", 0.82
    if chain_id == "club_itc" and len(tokens) >= 2 and tokens[0] == "itc":
        if tokens[1] not in {"limited", "office", "center", "centre", "tower"}:
            return 1, "ITC Hotels", 0.78
    if chain_id == "gha_discovery" and len(tokens) >= 2 and tokens[0] == "regent":
        # Regent under IHG covers specific flagship properties matched by full alias;
        # avoid false-matching generic "Regent View Inn" here.
        return None
    _ = normalized_name
    return None


def match_hotel_brand(
    property_name: str,
    rules: Sequence[HotelChainBrandRule] | None = None,
) -> HotelBrandMatch | None:
    """Deterministically match a hotel property name to a curated loyalty chain.

    Uses Unicode diacritic folding, word-boundary phrase matching, longest-phrase
    precedence, and contextual guards for short/generic hospitality words. Returns
    ``None`` for independent or unbranded properties.
    """
    normalized_name = normalize_property_name(property_name)
    if not normalized_name:
        return None

    active_rules: Sequence[HotelChainBrandRule]
    if rules is None:
        from core.loyalty.catalog_loader import default_hotel_brand_rules

        active_rules = default_hotel_brand_rules()
    else:
        active_rules = rules

    tokens = normalized_name.split(" ")
    padded = f" {normalized_name} "

    candidates: list[tuple[int, int, float, str, HotelChainBrandRule]] = []

    for rule in active_rules:
        for raw_alias in rule.brand_aliases:
            norm_alias = normalize_property_name(raw_alias)
            if not norm_alias or norm_alias in _AMBIGUOUS_SINGLE_WORD_ALIASES:
                continue
            alias_words = norm_alias.split(" ")
            needle = f" {norm_alias} "
            if needle in padded:
                word_count = len(alias_words)
                char_len = len(norm_alias)
                if word_count >= 2:
                    confidence = 0.95
                elif char_len >= 7:
                    confidence = 0.90
                else:
                    confidence = 0.85
                candidates.append((word_count, char_len, confidence, raw_alias, rule))

        contextual = _match_contextual_brand(normalized_name, tokens, rule.chain_id)
        if contextual is not None:
            word_rank, matched_label, ctx_conf = contextual
            candidates.append((word_rank, len(matched_label), ctx_conf, matched_label, rule))

    if not candidates:
        return None

    # Prefer highest word count, then longest alias text, then highest confidence,
    # then deterministic lexicographic tie-breaks.
    best = min(
        candidates,
        key=lambda item: (-item[0], -item[1], -item[2], item[4].chain_id, item[3]),
    )
    _, _, best_conf, best_brand, best_rule = best
    return HotelBrandMatch(
        matched_brand=best_brand,
        chain_id=best_rule.chain_id,
        program_id=best_rule.program_id,
        confidence=best_conf,
        provenance=best_rule.provenance,
    )
