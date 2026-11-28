"""Pure, deterministic airline & hotel loyalty ecosystem bridge."""

from core.loyalty.award_rules import (
    compare_direct_vs_ota_hotel,
    compute_hotel_award_stay_points,
    find_partner_booking_programs,
)
from core.loyalty.catalog_loader import (
    REFERENCE_CATALOG_PATH,
    default_alliance_partner_edges,
    default_hotel_award_stay_rules,
    default_hotel_brand_rules,
    hotel_award_stay_rule_for_program,
    load_loyalty_overlay_kb,
    load_loyalty_reference_catalog,
)
from core.loyalty.contracts import (
    AlliancePartnerEdge,
    DirectVsOtaLoyaltyComparison,
    HotelAwardStayCalculation,
    HotelAwardStayRule,
    HotelBrandMatch,
    HotelChainBrandRule,
    LoyaltyReferenceCatalog,
)
from core.loyalty.hotel_brands import match_hotel_brand, normalize_property_name

__all__ = [
    "REFERENCE_CATALOG_PATH",
    "AlliancePartnerEdge",
    "DirectVsOtaLoyaltyComparison",
    "HotelAwardStayCalculation",
    "HotelAwardStayRule",
    "HotelBrandMatch",
    "HotelChainBrandRule",
    "LoyaltyReferenceCatalog",
    "compare_direct_vs_ota_hotel",
    "compute_hotel_award_stay_points",
    "default_alliance_partner_edges",
    "default_hotel_award_stay_rules",
    "default_hotel_brand_rules",
    "find_partner_booking_programs",
    "hotel_award_stay_rule_for_program",
    "load_loyalty_overlay_kb",
    "load_loyalty_reference_catalog",
    "match_hotel_brand",
    "normalize_property_name",
]
