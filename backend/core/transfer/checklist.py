from core.models import LoyaltyProgram, TransferBonus, TransferPlan


def build_checklist(
    plan: TransferPlan,
    program: LoyaltyProgram,
    bonuses: dict[str, TransferBonus],
) -> list[str]:
    url = program.booking_url or "the loyalty program's official site"
    rows = [
        (
            "VERIFY (blocking): Confirm "
            f"{plan.award.cabin} award space for {plan.travelers} on "
            f"{plan.award.origin}->{plan.award.destination} for your selected dates at {url}. "
            "Do NOT transfer until you can see the seats. Transfers are irreversible."
        )
    ]
    if any(step.transfer_time_hours_max > 0 for step in plan.steps):
        rows.append(
            "Warning: award space can disappear during a non-instant transfer; "
            "prefer an instant path when the value gap is small."
        )
    for step in plan.steps:
        bonus = bonuses.get(step.bonus_applied or "")
        suffix = (
            f", includes bonus {bonus.id} expiring {bonus.valid_to.isoformat()}"
            if bonus is not None
            else ""
        )
        rows.append(
            f"Transfer {step.amount_source} {step.from_id} -> "
            f"{step.amount_dest} {step.to_id} "
            f"(typically {step.transfer_time_hours_typical}h, "
            f"up to {step.transfer_time_hours_max}h{suffix})."
        )
    rows.append(
        f"Book on {program.name} for "
        f"{plan.award.miles_cost}x{plan.travelers} miles + "
        f"{plan.total_fees_minor} {plan.award.fees_currency} minor units in fees."
    )
    if plan.leftover_miles:
        rows.append(f"Leftover: {plan.leftover_miles} miles will remain in {program.name}.")
    rows.append(
        f"Chart last verified {plan.award.provenance.last_verified.isoformat()}; "
        "award availability is never guaranteed by this tool."
    )
    return rows
