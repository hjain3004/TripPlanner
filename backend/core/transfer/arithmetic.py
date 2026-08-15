from core.models import FxRate, TransferEdge

MICRO_MAJOR_PER_MINOR = 10_000
BASIS_POINTS = 10_000
FX_RATE_MICRO = 1_000_000


def destination_units(source: int, edge: TransferEdge, bonus_bp: int = 0) -> int:
    return source * edge.ratio_to * (BASIS_POINTS + bonus_bp) // edge.ratio_from // BASIS_POINTS


def round_up_to_increment(value: int, increment: int) -> int:
    return ((value + increment - 1) // increment) * increment


def minimum_source_units(required_dest: int, edge: TransferEdge, bonus_bp: int = 0) -> int:
    if required_dest <= 0:
        return 0
    numerator = required_dest * edge.ratio_from * BASIS_POINTS
    denominator = edge.ratio_to * (BASIS_POINTS + bonus_bp)
    raw = (numerator + denominator - 1) // denominator
    source = round_up_to_increment(max(raw, edge.min_transfer), edge.increment)
    while destination_units(source, edge, bonus_bp) < required_dest:
        source += edge.increment
    return source


def redemption_value_micro(cash_price_minor: int, fees_minor: int, points: int) -> int:
    if points <= 0:
        return 0
    return max(0, cash_price_minor - fees_minor) * MICRO_MAJOR_PER_MINOR // points


def opportunity_cost_minor(points: int, value_micro_major_per_point: int) -> int:
    return points * value_micro_major_per_point // MICRO_MAJOR_PER_MINOR


def convert_minor(amount_minor: int, rate: FxRate) -> int:
    return amount_minor * rate.rate_micro // FX_RATE_MICRO
