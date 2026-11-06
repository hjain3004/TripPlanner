"""Explicit operator search -> rates workflow; no retries or booking tools.

Requires current OS-keychain credentials and explicit operator authorization.
Only normalized public fields are printed. Raw Markdown and signed rate
tokens remain in memory and are never written by this command.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime

from gateway.travel.adapters.gondola.dated_hotel_adapter import build_keychain_hotel_adapter
from gateway.travel.contracts import HotelSearchRequest, TravelerMix
from gateway.travel.errors import TravelGatewayError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location", required=True)
    parser.add_argument("--checkin", required=True, type=date.fromisoformat)
    parser.add_argument("--checkout", required=True, type=date.fromisoformat)
    parser.add_argument("--adults", type=int, default=1)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--display-currency", default="INR")
    parser.add_argument("--live-read-only", action="store_true")
    parser.add_argument("--confirm-zero-spend", action="store_true")
    args = parser.parse_args()
    if not args.live_read_only or not args.confirm_zero_spend:
        parser.error("Explicit read-only authorization and zero-spend confirmation are required")
    from gateway.travel.registry import gondola_kill_switch_active

    if gondola_kill_switch_active():
        parser.error("Gondola kill switch is active")
    request = HotelSearchRequest(
        city=args.location,
        check_in=args.checkin,
        check_out=args.checkout,
        travelers=TravelerMix(adults=args.adults),
        rooms=1,
        style="balanced",
        currency=args.display_currency,
    )
    adapter = build_keychain_hotel_adapter(
        plan_id=args.plan_id, now=lambda: datetime.now(UTC)
    )
    try:
        quotes = asyncio.run(adapter.search_hotels(request))
    except TravelGatewayError as exc:
        # Use the code only; provider error bodies may contain private text.
        print(json.dumps({"status": "unavailable", "code": exc.code}))
        raise SystemExit(1) from None
    print(
        json.dumps(
            {"status": "verify_required", "cost_eligible": False,
             "hotels": [quote.model_dump(mode="json") for quote in quotes]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
