# 18 — Card Acquisition & Welcome Offers

**Do not build during the Kernel MVP.** This spec depends on `17_accounts_and_persistence.md` for `WalletEntry.opened_on` and on a populated `card_acquisition_offers` table. It is specified now so the persistence layer stores the one field it needs.

The observation this spec serves: for most cardholders the largest single reward event of a card's life is its **welcome bonus**, not its ongoing earn rate. A joining bonus is typically worth several times a year of category spend, and it is available exactly once, inside a window measured in weeks. A trip is the natural moment it becomes reachable, because a trip concentrates a year's discretionary spend into one booking session.

That makes this the highest-value recommendation the product can make — and the one with the sharpest edges. Everything below exists to keep it useful without turning the product into a credit-card marketing surface.

## The two cases, in order of priority

**Case A — a card the user already holds, with an open welcome window.** No application, no eligibility guessing, no advice framing. The system knows `opened_on`, knows the minimum spend, and knows what this trip costs. It says: *"You opened this card 47 days ago. ₹18,400 of the ₹50,000 minimum spend remains and the window closes 12 September. Putting the flights here clears it."*

**Case B — a card the user does not hold.** Materially riskier: it requires an application, it depends on facts the system cannot know, and its upside is contingent on approval. Specified second, gated harder, and never allowed to outrank Case A or the strategy built from cards already held.

**Implement Case A first and ship it alone if Case B is not ready.** Case A is most of the value and carries almost none of the risk.

## 1. `card_acquisition_offers`

```python
class CardAcquisitionOffer(BaseModel):
    id: str
    card_id: str                          # the `cards` row this welcome offer belongs to
    title: str                            # verbatim from the issuer page
    bonus_points: int | None              # points-denominated welcome bonus
    bonus_currency_id: str | None         # which points currency (07 LoyaltyProgram.id)
    bonus_flat_minor: int | None          # cashback/voucher-denominated welcome bonus
    min_spend_minor: int                  # qualifying spend required
    spend_window_days: int                # measured from card open date, per T&C
    expected_approval_days: int           # application → decision (issuer-published or curated)
    expected_card_in_hand_days: int       # approval → physically usable card
    annual_fee_minor: int                 # first-year fee, may differ from Card.annual_fee_minor
    fee_waiver_condition: str | None      # "waived on ₹X spend in year 1"
    eligibility_exclusions: list[str]     # VERBATIM T&C strings, never paraphrased
    currency: str
    valid_to: date
    provenance: Provenance
```

`eligibility_exclusions` holds verbatim T&C text ("not available to customers who have held any HDFC credit card in the preceding 24 months") and is rendered verbatim. Paraphrasing an eligibility rule is how you tell someone they qualify when they do not.

Exactly one of `bonus_points` / `bonus_flat_minor` is set. Points-denominated bonuses are valued through the existing `PointValuation` machinery (01 §5) at the card's best path, and the report must state the assumed path — same rule as everywhere else.

## 2. Case A — welcome window status (held cards)

```python
class WelcomeWindowStatus(BaseModel):
    card_id: str
    wallet_entry_id: str
    opened_on: date | None
    window_closes_on: date | None
    days_remaining: int | None
    min_spend_minor: int
    qualifying_spend_to_date_minor: int | None   # user-entered; None if unknown
    trip_eligible_spend_minor: int               # from OptimizerResult, this card only
    shortfall_minor: int | None
    bonus_value_minor: int
    status: Literal["active", "closing_soon", "met", "expired", "unknown"]
```

`status="unknown"` whenever `opened_on` is `None` — the field is optional on `WalletEntry` (17) and most users will not fill it in. **An unknown window is rendered as unknown and never guessed.** Do not infer an open date from a statement day, a points balance, or anything else.

`closing_soon` threshold: ≤ 21 days remaining. Tier C, tune freely.

`qualifying_spend_to_date_minor` is user-entered and unverifiable. When it is `None`, the system states the full minimum and says it cannot see prior spend — it does not assume zero.

## 3. The money math (deterministic, no LLM)

Per non-negotiable #1, every number here is computed in Python and copied verbatim into prose. Integer minor units throughout; basis points for percentages; no floats.

```
bonus_value_minor      = bonus_flat_minor
                       | floor(bonus_points * best_valuation_micro_per_point / 10_000)
trip_earn_delta_minor  = benefit(trip | wallet + candidate) − benefit(trip | wallet)
net_first_year_minor   = bonus_value_minor + trip_earn_delta_minor − annual_fee_minor
```

`trip_earn_delta_minor` is computed by running the **existing optimizer twice** (02) — once with the current wallet, once with the candidate card added — and differencing `OptimizerResult`. Do not write a second, parallel benefit calculation. The delta inherits every property the optimizer already guarantees: cap fall-through, stacking order, determinism, provenance propagation.

`net_first_year_minor` may be negative. When it is, the card is not suggested — no exceptions, no "but the long-term value."

## 4. The timing gate (Case B)

The failure mode that makes naive versions of this feature useless: recommending a card that cannot physically arrive before the spend it is supposed to capture.

```
earliest_usable_date   = booking_date + expected_approval_days + expected_card_in_hand_days
window_closes_on       = earliest_usable_date + spend_window_days

Suggest ONLY IF all hold:
  1. earliest_usable_date  ≤  first_bookable_spend_date
  2. min_spend_minor       ≤  trip_eligible_spend_minor
  3. all trip spend counted in (2) falls on or before window_closes_on
  4. net_first_year_minor  >  0
  5. offer.valid_to        ≥  booking_date
```

Fail any one → the card is not suggested. The report says nothing rather than saying something hedged. If gate 1 fails only narrowly, the system may state the fact ("this card's welcome bonus would need ~3 weeks' lead time you don't have") but must not present it as an option.

## 5. What the system cannot know

Approval depends on credit score, income, existing issuer relationships, and prior product history. The system has none of these and must never model them.

- Never state or imply approval likelihood. No "you'll likely be approved," no scoring, no pre-qualification.
- Always render `eligibility_exclusions` verbatim alongside any Case B suggestion, framed so the user checks them against their own history.
- Never suppress a card because it *seems* unlikely to be approved, and never surface one because it seems likely. The system is not modelling the user's creditworthiness in either direction.
- Case B output is framed as **information about an offer**, not a recommendation to apply. Required phrasing pattern: "This card's current welcome bonus would be worth ₹X on this trip if you held it" — never "you should get this card."

## 6. Report placement

Case A appears inline in the payment strategy, because it changes which card a specific line should go on — that is optimizer output, not a suggestion.

Case B appears in a clearly separated section **below** the complete strategy built from held cards, never merged into it and never ranked against it. A user who ignores the section entirely must still get a complete, optimal plan from the cards they already have. That property is the test: if removing the Case B section degrades the plan, the feature has been built wrong.

## 7. Non-goals (hard)

No application submission or pre-filling. No pre-qualification or credit-check API. No credit score retrieval, storage, or inference. **No affiliate, referral, or tracked links** — consistent with 05's discovery non-goals; the product never participates in card-referral economics, which is precisely what keeps this recommendation trustworthy. No "you will be approved" claims. No churning guidance, no application-velocity strategy, no advice on gaming issuer eligibility rules. No suggestion ranked above the strategy from held cards. No LLM-generated number anywhere in this feature.

This is a student/portfolio project surfacing published offer terms with provenance. It is not financial advice, is not a comparison service, and earns nothing from any issuer.
