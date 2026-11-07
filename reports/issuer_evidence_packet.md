# Issuer Evidence Packet: Demonstration Wallet (HDFC Infinia + Axis Atlas)

**Milestone:** Real Issuer Evidence Packet & Primary Source Curation  
**Branch:** `codex/issuer-evidence-packet`  
**Base:** `origin/codex/financial-data-readiness` (containing PR #34 @ `00d9cf0`)  
**Status:** Evidence gathered from primary issuer sources, discrepancies flagged, draft welcome-offer data prepared against the Case B model, Sonnet acquisition manifest staged, and task-local review queue verified. Repository seeds and product code untouched.

---

## 1. Scope and Evidence Mode

This packet prepares the real primary-source issuer evidence required to replace the demonstration financial placeholders for TripWise's India → Singapore reference trip (`demo-del-sin`) and demonstration wallet (**HDFC Infinia Metal** and **Axis Bank ATLAS**).

- **Evidence Mode:** Research of public primary issuer documents directly from official issuer domains (`hdfc.bank.in`, `hdfcbank.com`, `axis.bank.in`, `axisbank.com`, and `traveledge.axisbank.co.in`).
- **No Crawling / Automated Bypasses:** No automated crawlers, headless automation, credentials, Firecrawl invocations, or third-party communications were used. Sonnet owns automated ingestion.
- **Task-Local Staging:** All raw captures, extraction configs, and staged SQLite databases are maintained strictly outside Git in `~/tripwise-ingestion-data/issuer-evidence-packet-20261106/` adhering to the project's private-data isolation protocol. Previous pilot and readiness data directories are preserved unmodified.
- **Drafting Identity:** All drafts and findings were prepared under operator identity `claude-evidence-curator`. No curator decisions or origin confirmations were executed as `himanshu`.

---

## 2. Priority Findings: Primary Official Evidence

### A. HDFC Infinia (Metal Edition)

| Fact / Field | Official Primary Value | Seed Value | Source Document & Quotation |
|---|---|---|---|
| **Annual / Joining Fee** (`annual_fee_minor`) | ₹12,500 + 18% GST (1,250,000 minor) | 1,250,000 minor | *HDFC Infinia Product Page:* "an annual renewal fee of ₹12,500 plus applicable taxes". Spend waiver: ₹10 Lakhs in preceding 12 months. |
| **Forex Markup** (`forex_markup_bp`) | **2.0%** (200 bp) | 200 bp | *HDFC Credit Card Schedule of Charges:* Preferential 2.0% markup for Infinia / Infinia Metal (standard cards: 3.5%). |
| **Tax on Markup** (`forex_markup_tax_bp`) | **18% GST** (1800 bp) | 1800 bp | *HDFC Bank MITC / Tariff of Charges:* 18% GST applies to all credit card fees, interest, and foreign currency markup. |
| **Card Network** (`network`) | Visa Infinite / Mastercard World Elite | visa | *HDFC Bank Infinia Card Agreement / Disclosures:* Issued on Visa Infinite and Mastercard World Elite. Seed 'visa' is supported. |
| **Base Earn Rate** (`base_earn`) | 5 pts per ₹150 (3.33% reward rate) | 5 pts / ₹150 | *HDFC Infinia Product Page:* "5 Reward Points per ₹150 spent". |
| **SmartBuy Portal Earn** (`reward_rules/infinia-portal`) | **10X** Hotels (33.3%), **5X** Flights (16.7%) | 10 pts per ₹100 | *HDFC SmartBuy Terms & Conditions:* Hotels earn 10X (1 Base + 9 Accelerated); Flights earn 5X (1 Base + 4 Accelerated). Accelerated points credit within 120 days. |
| **SmartBuy Earn Cap** (`cap.max_points`) | **15,000 pts/month** | 400,000 pts | *HDFC SmartBuy Terms & Conditions:* Overall accelerated Reward Points capped at 15,000 RP per calendar month. |
| **Portal Redemption** (`point_valuations/infinia-portal-val`) | ₹1.00 / point (1,000,000 micro-major) | ₹1.00 / point | *HDFC SmartBuy Terms:* 1 RP = ₹1.00 for flight/hotel bookings. Max 70% of booking value payable by points; max 1,500,000 points redeemable per month. |
| **Welcome Benefit** (Case B Model) | 12,500 Reward Points | None | *HDFC Infinia Terms:* 12,500 points upon realization of ₹12,500 joining fee and card activation. |

---

### B. Axis Bank ATLAS Credit Card

| Fact / Field | Official Primary Value | Seed Value | Source Document & Quotation |
|---|---|---|---|
| **Annual / Joining Fee** (`annual_fee_minor`) | ₹5,000 + 18% GST (500,000 minor) | 500,000 minor | *Axis Bank ATLAS Schedule of Charges:* Joining fee ₹5,000 + GST; renewal fee ₹5,000 + GST. Non-waivable. |
| **Forex Markup** (`forex_markup_bp`) | **3.5%** (350 bp) | **150 bp** | **CRITICAL CONFLICT:** *Axis Bank ATLAS Terms & Conditions / Schedule of Charges* establishes a **3.5%** foreign currency markup. The seed currently holds **1.5% (150 bp)**. For overseas Singapore transactions, this 200 bp difference substantially alters card ranking and net benefit. |
| **Tax on Markup** (`forex_markup_tax_bp`) | **18% GST** (1800 bp) | 1800 bp | *Axis Bank Credit Card MITC:* 18% GST applicable to all fees, interest, and forex transaction markup. |
| **Points Program Identity** | **EDGE Miles** (`axis-edge-miles`) | `voyager-prime` / unlinked | *Axis Bank ATLAS Product Page & Travel EDGE Portal:* Dedicated loyalty currency is "EDGE Miles", distinct from standard Axis EDGE REWARDS. |
| **Base Earn Rate** (`base_earn`) | 2 EDGE Miles per ₹100 | 2 pts / ₹100 | *Axis Bank ATLAS Terms & Conditions:* "Earn 2 EDGE Miles per ₹100 spent on all other categories". |
| **Travel Earn Rate** (`reward_rules/atlas-travel`) | 5 EDGE Miles per ₹100 | 5 pts / ₹100 | *Axis Bank ATLAS Terms & Conditions:* "Earn 5 EDGE Miles per ₹100 spent on travel - airlines and hotels, and Travel EDGE portal". |
| **Travel Earn Cap** (`cap.max_points`) | ₹2,00,000 spend/mo (10,000 miles cap) | 100,000 pts | *Axis Bank ATLAS Terms & Conditions:* 5X rate applies up to ₹2,00,000 monthly spend (max 10,000 accelerated EDGE Miles/month); standard 2 EDGE Miles/₹100 thereafter. |
| **Excluded Categories** | Excluded MCCs | Empty / generic | *Axis Bank ATLAS Terms & Conditions:* Fuel (5541, 5542), Rent (6513), Wallet (6540), Insurance (6300, 5960), Government (9399), Utilities/Telecom, Gold/Jewellery earn 0 miles and are excluded from tier spends. |
| **Portal Valuation** (`point_valuations/atlas-portal-val`) | ₹1.00 / point (1,000,000 micro-major) | ₹1.00 / point | *Axis Travel EDGE Terms:* 1 EDGE Mile = ₹1.00 for flight/hotel bookings on Travel EDGE. |
| **Partner Transfer Ratio** | **1:2** (1 EDGE Mile = 2 Partner Points/Miles) | 1:2 | *Axis Miles Transfer Terms:* 1 EDGE Mile converts to 2 Partner Points (Accor ALL, Singapore Airlines KrisFlyer, Air India, Marriott, Qatar Airways, etc.). Subject to 30,000 Group A and 150,000 overall annual caps. |
| **Welcome Benefit** (Case B Model) | 2,500 EDGE Miles | None | *Axis Bank ATLAS Terms & Conditions:* 2,500 EDGE Miles upon first transaction within 37 days of issuance, subject to payment of ₹5,000 joining fee. |

---

## 3. Discrepancies and Representation Gaps

1. **Axis Atlas Forex Markup Contradiction:**
   - **Official Disclosures:** 3.5% (350 bp) + 18% GST.
   - **Current Seed:** 150 bp (1.5%).
   - **Impact:** Seed significantly underestimates overseas transaction cost. A curator decision is required to align the seed with the official 350 bp rate.
2. **HDFC SmartBuy Multiplier vs Flat Rule:**
   - The seed models SmartBuy as a flat `10 pts per ₹100` on flights and hotels.
   - The primary issuer terms define a differential rate: `10X` on Hotels (33.3% return) and `5X` on Flights (16.7% return), under a calendar-month accelerated cap of 15,000 Reward Points (seed currently holds 400,000 points).
3. **Unrepresentable Constraints:**
   - **HDFC Infinia Lounge Entitlement:** The product page promises unlimited international lounge access via Priority Pass. The schema field `lounge_intl_visits_per_year` is an integer; the seed holds 12.
   - **SmartBuy Points Payment Floor / Ceiling:** Bookings require a minimum 30% cash/card copay (max 70% points redemption) and cap redemptions at 1,500,000 points per month. `PointValuation` currently has no structured fields for copay floor or monthly ceiling.
4. **Welcome-Offer Ingestion Schema Gap:**
   - The core ingestion engine supports 4 tables: `cards`, `offers`, `point_valuations`, and `reward_rules`.
   - Candidate welcome offers for unheld cards require the Case B `CardAcquisitionOffer` schema (`min_spend_minor`, `spend_window_days`, `lead_time`, `eligibility_exclusions`). Staged draft data has been formatted against the Case B model in `welcome_offers_case_b.json` outside Git.
5. **Card-to-Loyalty-Program Linkage:**
   - Neither `Card` nor `PointValuation` carries a loyalty program identifier.
   - In the seed, the demo wallet points balance references `voyager-prime`, which does not exist in `loyalty_programs`. Real program identities (`axis-edge-miles` and `hdfc-reward-points`) must be registered as `card_currency` loyalty programs before points bonuses can be valued deterministically.

---

## 4. Staged Drafts & Review Queue State

The local staging database at `~/tripwise-ingestion-data/issuer-evidence-packet-20261106/data/ingestion.sqlite` preserves the review queue:
- **Pending Draft 1:** `cards/hdfc-infinia` (5 fields: `annual_fee_minor`, `base_earn.points`, `base_earn.per_amount_minor`, `issuer`, `name`).
- **Pending Draft 2:** `point_valuations/infinia-portal-val` (1 field: `value_micro_major_per_point`).
- **Curator Findings:** 11 detailed findings loaded in `findings.yaml` documenting forex markup, tax, SmartBuy multiplier structures, and the Axis Atlas forex contradiction.
- **Candidate Case B Offers:** Prepared in `cfg/welcome_offers_case_b.json` for Axis Atlas (2,500 EDGE Miles, 37-day window, ₹5,000 fee) and HDFC Infinia (12,500 RP, 90-day window, ₹12,500 fee).

---

## 5. Handoff to Sonnet Automated Acquisition

A machine-readable manifest has been placed in `~/tripwise-ingestion-data/issuer-evidence-packet-20261106/cfg/sonnet_handoff.json` detailing the primary acquisition targets:

1. **`https://www.hdfc.bank.in/credit-cards/infinia-credit-card`**  
   - *Class:* `card_page` | *Fields:* Fees, base earn, welcome bonus terms.  
   - *Policy:* `hdfc-bank-in-manual-card-page` (manual capture only). Automated access **requires owner review**.
2. **`https://www.hdfcbank.com/personal/resources/rates/credit-card-fees-and-charges`**  
   - *Class:* `card_page` | *Fields:* Preferential 2.0% forex markup, GST tax treatment.  
   - *Policy:* None. Automated access **requires owner review**.
3. **`https://offers.smartbuy.hdfcbank.com/`**  
   - *Class:* `offer_page` | *Fields:* 10X Hotels / 5X Flights, 15,000 RP monthly cap, 70% redemption cap.  
   - *Policy:* None. Automated access **requires owner review**.
4. **`https://www.axis.bank.in/cards/credit-card/axis-bank-atlas-credit-card`**  
   - *Class:* `card_page` | *Fields:* Fees, base earn, travel earn, welcome offer terms.  
   - *Policy:* None (public `robots.txt` permits root `/`). Automated access **requires owner review**.
5. **`https://www.axisbank.com/docs/default-source/default-document-library/axis-bank-atlas-credit-card-terms-and-conditions.pdf`**  
   - *Class:* `tnc_pdf` | *Fields:* 3.5% forex markup, ₹2L monthly travel cap, category exclusions.  
   - *Policy:* None. Automated access **requires owner review**.
6. **`https://traveledge.axisbank.co.in/`**  
   - *Class:* `offer_page` | *Fields:* 1:1 portal redemption, 1:2 partner transfer ratios and annual caps.  
   - *Policy:* None. Automated access **requires owner review**.

---

## 6. Precise Decisions Required from the Human Owner

1. **Acknowledge and Resolve the Axis Atlas Forex Discrepancy:** Decide whether to update `cards/axis-atlas:forex_markup_bp` from `150` to the evidenced `350` (3.5%).
2. **Review and Attest Source Policies:** Create and review source policies for `axis.bank.in` and HDFC rate sheets, deciding whether automated access is permitted for Sonnet.
3. **Decide Staged HDFC Drafts:** Execute `decision` for `cards/hdfc-infinia` and `point_valuations/infinia-portal-val` using owner credentials.
4. **Representational Governance:**
   - Decide how to represent "unlimited" lounge visits in integer schema fields.
   - Decide how to split SmartBuy 10X/5X flights vs hotels in `reward_rules`.
   - Register real program identities (`axis-edge-miles`, `hdfc-reward-points`) in `loyalty_programs`.
