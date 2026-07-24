"""SQLAlchemy schema + the ``KnowledgeBase`` read facade (spec 01 §10).

The optimizer and agents never write SQL; they call typed methods on
``KnowledgeBase``. The facade is built either from in-memory Pydantic models
(``from_models`` — used by the golden harness) or loaded from the seeded SQLite
DB (``load_kb`` — used at runtime, M2+).

Storage choice (Tier-C, logged in DEVIATIONS): one table per model with the
spec-01 §10 index columns broken out as real columns, plus a ``payload`` TEXT
column holding the canonical ``model_dump_json()`` for lossless round-trip. TEXT
JSON maps cleanly to Postgres JSONB later; the index columns give the required
indices (``reward_rules(card_id)``, ``offers(merchant)``, ``offers(valid_to)``,
``poi(city)``).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel
from sqlalchemy import Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from core.models import (
    Area,
    AwardChartEntry,
    Card,
    FxRate,
    LoyaltyProgram,
    Offer,
    POI,
    PointValuation,
    RedemptionPath,
    RewardRule,
    SampleFlight,
    SampleHotel,
    SpendCategory,
    TransferBonus,
    TransferEdge,
)
from core.models import (
    Channel as ChannelEnum,
)

SEEDS_DIR = Path(__file__).parent / "seeds"
DB_PATH = Path(__file__).parent / "tripwise.sqlite"

# --------------------------------------------------------------------------- #
# SQLAlchemy schema                                                            #
# --------------------------------------------------------------------------- #


class Base(DeclarativeBase):
    pass


class CardRow(Base):
    __tablename__ = "cards"
    id: Mapped[str] = mapped_column(primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class RewardRuleRow(Base):
    __tablename__ = "reward_rules"
    id: Mapped[str] = mapped_column(primary_key=True)
    card_id: Mapped[str] = mapped_column(index=True)
    payload: Mapped[str] = mapped_column(Text)


class OfferRow(Base):
    __tablename__ = "offers"
    id: Mapped[str] = mapped_column(primary_key=True)
    merchant: Mapped[str] = mapped_column(index=True)
    valid_to: Mapped[str] = mapped_column(index=True)  # ISO date string
    payload: Mapped[str] = mapped_column(Text)


class PointValuationRow(Base):
    __tablename__ = "point_valuations"
    id: Mapped[str] = mapped_column(primary_key=True)
    card_id: Mapped[str] = mapped_column(index=True)
    payload: Mapped[str] = mapped_column(Text)


class POIRow(Base):
    __tablename__ = "pois"
    id: Mapped[str] = mapped_column(primary_key=True)
    city: Mapped[str] = mapped_column(index=True)
    payload: Mapped[str] = mapped_column(Text)


class AreaRow(Base):
    __tablename__ = "areas"
    id: Mapped[str] = mapped_column(primary_key=True)
    city: Mapped[str] = mapped_column(index=True)
    payload: Mapped[str] = mapped_column(Text)


class SampleFlightRow(Base):
    __tablename__ = "sample_flights"
    id: Mapped[str] = mapped_column(primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class SampleHotelRow(Base):
    __tablename__ = "sample_hotels"
    id: Mapped[str] = mapped_column(primary_key=True)
    city: Mapped[str] = mapped_column(index=True)
    payload: Mapped[str] = mapped_column(Text)


class FxRow(Base):
    __tablename__ = "fx_rates"
    id: Mapped[str] = mapped_column(primary_key=True)  # f"{base}:{quote}"
    payload: Mapped[str] = mapped_column(Text)


class LoyaltyProgramRow(Base):
    __tablename__ = "loyalty_programs"
    id: Mapped[str] = mapped_column(primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class TransferEdgeRow(Base):
    __tablename__ = "transfer_edges"
    id: Mapped[str] = mapped_column(primary_key=True)
    from_id: Mapped[str] = mapped_column(index=True)
    to_id: Mapped[str] = mapped_column(index=True)
    payload: Mapped[str] = mapped_column(Text)


class TransferBonusRow(Base):
    __tablename__ = "transfer_bonuses"
    id: Mapped[str] = mapped_column(primary_key=True)
    edge_id: Mapped[str] = mapped_column(index=True)
    valid_from: Mapped[str] = mapped_column(index=True)
    valid_to: Mapped[str] = mapped_column(index=True)
    payload: Mapped[str] = mapped_column(Text)


class AwardChartEntryRow(Base):
    __tablename__ = "award_chart_entries"
    id: Mapped[str] = mapped_column(primary_key=True)
    program_id: Mapped[str] = mapped_column(index=True)
    origin: Mapped[str] = mapped_column(index=True)
    destination: Mapped[str] = mapped_column(index=True)
    cabin: Mapped[str] = mapped_column(index=True)
    trip_type: Mapped[str] = mapped_column(index=True)
    payload: Mapped[str] = mapped_column(Text)


# --------------------------------------------------------------------------- #
# KnowledgeBase facade                                                         #
# --------------------------------------------------------------------------- #


class KnowledgeBase:
    """Typed, read-only view over the knowledge base (spec 01 §10).

    Deterministic: every collection accessor returns rows in a stable order
    (sorted by id) so the optimizer's output is byte-reproducible.
    """

    def __init__(
        self,
        *,
        cards: list[Card],
        reward_rules: list[RewardRule],
        offers: list[Offer],
        point_valuations: list[PointValuation],
        fx_rates: list[FxRate] | None = None,
        pois: list[POI] | None = None,
        areas: list[Area] | None = None,
        sample_flights: list[SampleFlight] | None = None,
        sample_hotels: list[SampleHotel] | None = None,
        loyalty_programs: list[LoyaltyProgram] | None = None,
        transfer_edges: list[TransferEdge] | None = None,
        transfer_bonuses: list[TransferBonus] | None = None,
        award_chart_entries: list[AwardChartEntry] | None = None,
    ) -> None:
        self._cards: dict[str, Card] = {c.id: c for c in cards}
        self._rules_by_card: dict[str, list[RewardRule]] = {}
        for rule in reward_rules:
            self._rules_by_card.setdefault(rule.card_id, []).append(rule)
        self._offers: list[Offer] = sorted(offers, key=lambda o: o.id)
        self._valuations_by_card: dict[str, list[PointValuation]] = {}
        for val in point_valuations:
            self._valuations_by_card.setdefault(val.card_id, []).append(val)
        self._fx: dict[tuple[str, str], FxRate] = {
            (f.base, f.quote): f for f in (fx_rates or [])
        }
        self._pois: list[POI] = sorted(pois or [], key=lambda p: p.id)
        self._areas: list[Area] = sorted(areas or [], key=lambda a: a.id)
        self._flights: list[SampleFlight] = sorted(sample_flights or [], key=lambda f: f.id)
        self._hotels: list[SampleHotel] = sorted(sample_hotels or [], key=lambda h: h.id)
        self._programs: dict[str, LoyaltyProgram] = {
            p.id: p for p in sorted(loyalty_programs or [], key=lambda p: p.id)
        }
        self._transfer_edges: list[TransferEdge] = sorted(
            transfer_edges or [], key=lambda e: e.id
        )
        self._transfer_bonuses: list[TransferBonus] = sorted(
            transfer_bonuses or [], key=lambda b: b.id
        )
        self._award_chart_entries: list[AwardChartEntry] = sorted(
            award_chart_entries or [], key=lambda a: a.id
        )

    # -- construction ------------------------------------------------------- #

    @classmethod
    def from_models(
        cls,
        *,
        cards: list[Card],
        reward_rules: list[RewardRule],
        offers: list[Offer],
        point_valuations: list[PointValuation],
        fx_rates: list[FxRate] | None = None,
        pois: list[POI] | None = None,
        areas: list[Area] | None = None,
        sample_flights: list[SampleFlight] | None = None,
        sample_hotels: list[SampleHotel] | None = None,
        loyalty_programs: list[LoyaltyProgram] | None = None,
        transfer_edges: list[TransferEdge] | None = None,
        transfer_bonuses: list[TransferBonus] | None = None,
        award_chart_entries: list[AwardChartEntry] | None = None,
    ) -> KnowledgeBase:
        return cls(
            cards=cards,
            reward_rules=reward_rules,
            offers=offers,
            point_valuations=point_valuations,
            fx_rates=fx_rates,
            pois=pois,
            areas=areas,
            sample_flights=sample_flights,
            sample_hotels=sample_hotels,
            loyalty_programs=loyalty_programs,
            transfer_edges=transfer_edges,
            transfer_bonuses=transfer_bonuses,
            award_chart_entries=award_chart_entries,
        )

    # -- cards & rules ------------------------------------------------------ #

    def card(self, card_id: str) -> Card:
        return self._cards[card_id]

    def has_card(self, card_id: str) -> bool:
        return card_id in self._cards

    def cards(self) -> list[Card]:
        return [self._cards[cid] for cid in sorted(self._cards)]

    def rules_for_card(self, card_id: str) -> list[RewardRule]:
        return sorted(self._rules_by_card.get(card_id, []), key=lambda r: r.id)

    def rules_for_cards(self, card_ids: list[str]) -> list[RewardRule]:
        out: list[RewardRule] = []
        for cid in card_ids:
            out.extend(self.rules_for_card(cid))
        return out

    # -- valuations --------------------------------------------------------- #

    def valuations_for_card(self, card_id: str) -> list[PointValuation]:
        return sorted(self._valuations_by_card.get(card_id, []), key=lambda v: v.id)

    def best_valuation(self, card_id: str) -> tuple[int, RedemptionPath] | None:
        """Max value per point for the card (spec 01 §5 / 02 §5 MVP simplification).

        Tie-break by path name so the assumed redemption path is deterministic.
        """
        vals = self._valuations_by_card.get(card_id)
        if not vals:
            return None
        best = max(vals, key=lambda v: (v.value_micro_major_per_point, _neg_path(v.path)))
        return best.value_micro_major_per_point, best.path

    def best_valuation_obj(self, card_id: str) -> PointValuation | None:
        """The PointValuation row backing ``best_valuation`` (for provenance)."""
        vals = self._valuations_by_card.get(card_id)
        if not vals:
            return None
        return max(vals, key=lambda v: (v.value_micro_major_per_point, _neg_path(v.path)))

    # -- offers ------------------------------------------------------------- #

    def offers_matching(
        self,
        merchant: str | None,
        channel: ChannelEnum,
        category: SpendCategory,
        on_date: date,
    ) -> list[Offer]:
        """Merchant/channel/category/date-valid candidates (spec 01 §10, 02 §6).

        Card / issuer / network eligibility, ``min_txn`` and ``uses_per_card`` are
        applied later in ``optimizer/offers.py`` against the concrete card & amount.
        ``merchant is None`` matches nothing (spec 02 §6).
        """
        if merchant is None:
            return []
        needle = merchant.casefold()
        out = [
            o
            for o in self._offers
            if o.merchant.casefold() == needle
            and channel in o.channels
            and category in o.categories
            and o.valid_to >= on_date
        ]
        return out  # already id-sorted (self._offers is sorted)

    # -- destination data --------------------------------------------------- #

    def pois(self, city: str, tags: list[str] | None = None) -> list[POI]:
        wanted = set(tags or [])
        return [
            p
            for p in self._pois
            if p.city == city and (not wanted or wanted.issubset(set(p.tags)))
        ]

    def areas(self, city: str) -> list[Area]:
        return [a for a in self._areas if a.city == city]

    def fx_rate(self, base: str, quote: str) -> FxRate | None:
        return self._fx.get((base, quote))

    # -- transfer facts ----------------------------------------------------- #

    def programs(self) -> list[LoyaltyProgram]:
        return [self._programs[pid] for pid in sorted(self._programs)]

    def program(self, program_id: str) -> LoyaltyProgram:
        return self._programs[program_id]

    def edges_from(self, currency_ids: list[str]) -> list[TransferEdge]:
        wanted = set(currency_ids)
        return [edge for edge in self._transfer_edges if edge.from_id in wanted]

    def bonuses_active(self, edge_ids: list[str], on_date: date) -> list[TransferBonus]:
        wanted = set(edge_ids)
        return [
            bonus
            for bonus in self._transfer_bonuses
            if bonus.edge_id in wanted and bonus.valid_from <= on_date <= bonus.valid_to
        ]

    def award_entries(
        self, origin: str, destination: str, cabin: str, trip_type: str
    ) -> list[AwardChartEntry]:
        origin_key = origin.casefold()
        destination_key = destination.casefold()
        cabin_key = cabin.casefold()
        trip_type_key = trip_type.casefold()
        return [
            award
            for award in self._award_chart_entries
            if award.origin.casefold() == origin_key
            and award.destination.casefold() == destination_key
            and award.cabin.casefold() == cabin_key
            and award.trip_type.casefold() == trip_type_key
        ]


def _neg_path(path: RedemptionPath) -> str:
    # For deterministic max() tie-break: prefer lexicographically smallest path
    # among equal values by negating the comparison via a wrapper string.
    return path.value


# --------------------------------------------------------------------------- #
# Seed loading (YAML -> SQLite) and DB -> KnowledgeBase                        #
# --------------------------------------------------------------------------- #

_T = TypeVar("_T", bound=BaseModel)

def _load(path: Path, model: type[_T]) -> list[_T]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or []
    return [model.model_validate(row) for row in raw]


def seed_database(seeds_dir: Path = SEEDS_DIR, db_path: Path = DB_PATH) -> dict[str, int]:
    """Create the schema and load every seeds/*.yaml into SQLite. Returns row counts."""
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    counts: dict[str, int] = {}
    with Session(engine) as session:
        cards = _load(seeds_dir / "cards.yaml", Card)
        for c in cards:
            session.add(CardRow(id=c.id, payload=c.model_dump_json()))
        counts["cards"] = len(cards)

        rules = _load(seeds_dir / "reward_rules.yaml", RewardRule)
        for r in rules:
            session.add(RewardRuleRow(id=r.id, card_id=r.card_id, payload=r.model_dump_json()))
        counts["reward_rules"] = len(rules)

        offers = _load(seeds_dir / "offers.yaml", Offer)
        for o in offers:
            session.add(
                OfferRow(
                    id=o.id,
                    merchant=o.merchant,
                    valid_to=o.valid_to.isoformat(),
                    payload=o.model_dump_json(),
                )
            )
        counts["offers"] = len(offers)

        vals = _load(seeds_dir / "point_valuations.yaml", PointValuation)
        for v in vals:
            session.add(PointValuationRow(id=v.id, card_id=v.card_id, payload=v.model_dump_json()))
        counts["point_valuations"] = len(vals)

        pois = _load(seeds_dir / "pois.yaml", POI)
        for poi in pois:
            session.add(POIRow(id=poi.id, city=poi.city, payload=poi.model_dump_json()))
        counts["pois"] = len(pois)

        areas = _load(seeds_dir / "areas.yaml", Area)
        for a in areas:
            session.add(AreaRow(id=a.id, city=a.city, payload=a.model_dump_json()))
        counts["areas"] = len(areas)

        flights = _load(seeds_dir / "sample_flights.yaml", SampleFlight)
        for f in flights:
            session.add(SampleFlightRow(id=f.id, payload=f.model_dump_json()))
        counts["sample_flights"] = len(flights)

        hotels = _load(seeds_dir / "sample_hotels.yaml", SampleHotel)
        for h in hotels:
            session.add(SampleHotelRow(id=h.id, city=h.city, payload=h.model_dump_json()))
        counts["sample_hotels"] = len(hotels)

        fx = _load(seeds_dir / "fx_rates.yaml", FxRate)
        for rate in fx:
            session.add(FxRow(id=f"{rate.base}:{rate.quote}", payload=rate.model_dump_json()))
        counts["fx_rates"] = len(fx)

        programs = _load(seeds_dir / "loyalty_programs.yaml", LoyaltyProgram)
        for program in programs:
            session.add(LoyaltyProgramRow(id=program.id, payload=program.model_dump_json()))
        counts["loyalty_programs"] = len(programs)

        edges = _load(seeds_dir / "transfer_edges.yaml", TransferEdge)
        for edge in edges:
            session.add(
                TransferEdgeRow(
                    id=edge.id,
                    from_id=edge.from_id,
                    to_id=edge.to_id,
                    payload=edge.model_dump_json(),
                )
            )
        counts["transfer_edges"] = len(edges)

        bonuses = _load(seeds_dir / "transfer_bonuses.yaml", TransferBonus)
        for bonus in bonuses:
            session.add(
                TransferBonusRow(
                    id=bonus.id,
                    edge_id=bonus.edge_id,
                    valid_from=bonus.valid_from.isoformat(),
                    valid_to=bonus.valid_to.isoformat(),
                    payload=bonus.model_dump_json(),
                )
            )
        counts["transfer_bonuses"] = len(bonuses)

        awards = _load(seeds_dir / "award_chart_entries.yaml", AwardChartEntry)
        for award in awards:
            session.add(
                AwardChartEntryRow(
                    id=award.id,
                    program_id=award.program_id,
                    origin=award.origin,
                    destination=award.destination,
                    cabin=award.cabin,
                    trip_type=award.trip_type,
                    payload=award.model_dump_json(),
                )
            )
        counts["award_chart_entries"] = len(awards)

        session.commit()
    return counts


def load_kb(db_path: Path = DB_PATH) -> KnowledgeBase:
    """Load a KnowledgeBase from the seeded SQLite DB (runtime path, M2+)."""
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        cards = [Card.model_validate_json(r.payload) for r in session.scalars(select(CardRow))]
        rules = [
            RewardRule.model_validate_json(r.payload) for r in session.scalars(select(RewardRuleRow))
        ]
        offers = [Offer.model_validate_json(r.payload) for r in session.scalars(select(OfferRow))]
        vals = [
            PointValuation.model_validate_json(r.payload)
            for r in session.scalars(select(PointValuationRow))
        ]
        fx = [FxRate.model_validate_json(r.payload) for r in session.scalars(select(FxRow))]
        pois = [POI.model_validate_json(r.payload) for r in session.scalars(select(POIRow))]
        areas = [Area.model_validate_json(r.payload) for r in session.scalars(select(AreaRow))]
        flights = [
            SampleFlight.model_validate_json(r.payload)
            for r in session.scalars(select(SampleFlightRow))
        ]
        hotels = [
            SampleHotel.model_validate_json(r.payload)
            for r in session.scalars(select(SampleHotelRow))
        ]
        programs = [
            LoyaltyProgram.model_validate_json(r.payload)
            for r in session.scalars(select(LoyaltyProgramRow))
        ]
        edges = [
            TransferEdge.model_validate_json(r.payload)
            for r in session.scalars(select(TransferEdgeRow))
        ]
        bonuses = [
            TransferBonus.model_validate_json(r.payload)
            for r in session.scalars(select(TransferBonusRow))
        ]
        awards = [
            AwardChartEntry.model_validate_json(r.payload)
            for r in session.scalars(select(AwardChartEntryRow))
        ]
    return KnowledgeBase.from_models(
        cards=cards,
        reward_rules=rules,
        offers=offers,
        point_valuations=vals,
        fx_rates=fx,
        pois=pois,
        areas=areas,
        sample_flights=flights,
        sample_hotels=hotels,
        loyalty_programs=programs,
        transfer_edges=edges,
        transfer_bonuses=bonuses,
        award_chart_entries=awards,
    )


def _main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "seed":
        counts = seed_database()
        total = sum(counts.values())
        print(f"Seeded {DB_PATH} ({total} rows):")
        for stem, n in counts.items():
            print(f"  {stem:18s} {n}")
        return 0
    print("usage: python -m core.db seed", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
