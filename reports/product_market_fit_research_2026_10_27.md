# TripPlanner: product-market fit, competitors, research, and engineering signal

Research date: **27 October 2026** (America/Los_Angeles). This is a research and product-owner assessment, not an implementation milestone or a change to the approved build order.

## Assessment

TripPlanner has a credible **problem hypothesis** and substantial portfolio engineering, but product-market fit is **not established by the evidence reviewed**. Neither competitor activity nor a passing software gate demonstrates that travelers will use this product, trust its advice, or return for another trip.

The strongest proposed position is:

> **For Indian travelers with an existing card-and-points wallet, turn one planned trip into an explainable payment and redemption plan: what to pay now, which card to use, which points to keep or transfer, and what still needs verification.**

This is a positioning hypothesis. “The only travel website that knows your credit cards” is not supportable. “AI trip planning,” “cash versus points,” “best card,” “personalization,” and even whole-trip assistance already have substantial competition.

For hiring, the strongest story is a **deterministic decision system with bounded language assistance and explicit evidence boundaries**. A senior Expedia or Amex engineer could find that compelling if the implementation, limitations, benchmark results, and ownership can withstand questions. No research can predict a particular interviewer's reaction.

## Method and limits

- Reviewed official company announcements, product documentation, support pages, publisher disclosures, academic publication records, and selected full-paper sections. Company assertions are evidence of advertised capabilities or announced direction, not independently tested performance.
- Examined the current checkout on `codex/docs-fable-handoff`, HEAD `b4f43ec`, including current-state documentation, the latest Gondola response-contract report, optimizer allocation, transfer arithmetic/pathfinding, itinerary composition, explainer grounding, planning repository, and corresponding evaluation sources.
- Separate implementation worktrees are not assumed to be merged or complete. No website URL was provided; this is not a live visual/usability audit of a deployed site.
- No competitor account, paid subscription, booking, transfer, credential flow, user interview, or live product-provider call was performed. Public internet research only. No fresh test-suite result, traffic, conversion, or savings outcome is claimed.
- “Not documented in the reviewed sources” means unknown. It does not establish that a competitor lacks a feature or internal engineering capability. This was a targeted landscape review, not an exhaustive census of every travel/rewards product.

## 1. What the named companies are doing

| Company | Current public evidence | What they are doing well / implication for TripPlanner |
|---|---|---|
| **Expedia Group** | Its May 2026 announcement covers natural-language planning, smarter comparison, and integrations across the journey. It **acquired Layla on 31 July 2026**, bringing conversational itinerary planning together with Expedia's supply and booking technology. Its ChatGPT product page separates exploration from booking on Expedia. | Distribution, supply, servicing, and the path from inspiration to booking matter more than a chatbot alone. Do not pitch conversational itineraries or end-to-end planning as exclusive. [Explore announcement](https://www.expedia.com/newsroom/expedia-group-unveils-new-ai-experiences-expands-travel-ecosystem-and-launches-philanthropy-program-at-explore-2026/), [Layla acquisition](https://ir.expediagroup.com/news-and-events/news/news-details/2026/Expedia-Group-acquires-Layla-accelerating-its-AI-powered-trip-planning-and-booking-strategy/default.aspx), [ChatGPT experience](https://www.expedia.com/product/expedia-in-chatgpt/) |
| **Booking.com / Booking Holdings** | Booking.com describes embedded AI assistance, Smart Messenger/Auto-Reply, and accommodation discovery in ChatGPT. Separately, **Booking Holdings announced Vayo on 14 October 2026**: a private-beta whole-trip agent combining reservations across providers, with price monitoring and change implications. Direct booking and other extensions are described as future plans. | Whole-trip coordination and cross-provider organization are being pursued by incumbents. Vayo is a Booking Holdings company, not evidence that every Booking.com customer already has these capabilities. [Booking.com announcement](https://news.booking.com/bookingcom-debuts-agentic-ai-innovations-adding-to-its-robust-suite-of-genai-tools-for-customers/), [Vayo announcement](https://www.bookingholdings.com/press-releases/booking-holdings-launches-vayo-with-planned-100m-investment/) |
| **MakeMyTrip** | February 2026 OpenAI collaboration; its May FY26 release says Myra can support search through paid booking in a conversational interface, including voice. The company reports substantial usage from smaller Indian cities. | Local languages, familiar distribution, and completing useful tasks are strong advantages. “India-focused AI travel” is insufficient differentiation. Reported adoption is company evidence, not proof that your target wallet segment is served. [OpenAI collaboration](https://investors.mmtcdn.com/Make_My_Trip_Deepens_AI_First_Strategy_with_Open_AI_Collaboration_152a91fca9.pdf), [FY26 release](https://investors.mmtcdn.com/MMYT_Earnings_Press_release_Q4_FY_26_c47af74a39.pdf) |
| **The Points Guy** | Rewards education and travel/card content remain available. Its official support FAQ, updated February 2026, says the **TPG app is paused**, with no specific replacement timeline. | Editorial authority and education are important substitutes for decision software. Do not compare your product to a presumed currently operating TPG wallet app. The pause is not evidence that rewards software has no demand, and its cause is not established here. [Official app FAQ](https://thepointsguy.zendesk.com/hc/en-us/articles/46361712040980-TPG-App-FAQ) |
| **NerdWallet** | Publishes points valuations and offers a cash-versus-points flight calculator. Its disclosure explains partner compensation and distinguishes placement considerations from editorial opinions. | Clear education and calculators already solve parts of your problem. Your opportunity is executing a specific trip decision across the wallet, rather than merely publishing another valuation. Affiliate economics do not prove biased advice. [Valuation guidance](https://www.nerdwallet.com/travel/learn/how-to-use-points-valuations), [Disclosure](https://www.nerdwallet.com/advertiser-disclosure) |

The common direction is **personalization embedded into a useful workflow, backed by inventory and distribution**. That is my synthesis of these sources, not a claim that the companies use the same architecture.

## 2. The more direct competitive set

The closest competitor is often a rewards tool plus an itinerary tool plus the user's spreadsheet, rather than Expedia alone.

| Product | Advertised overlap | Implication |
|---|---|---|
| **Gondola** | Hotel cash/points decisions, loyalty aggregation, direct-booking compatibility, rewards stacking, rate monitoring, and AI/MCP access. | A particularly close overlap and a potential dependency. Depending on it for evidence does not make its capabilities exclusive to you. Its advertised return metrics combine estimated points value and cash back; they should not be treated as pure cash savings. [Product explanation](https://www.gondola.ai/what-is-gondola), [Help center](https://www.gondola.ai/help) |
| **SaveSage** | Indian cards, rewards/loyalty management, transfer/redemption options, AI assistance, expert consultation, and points-based flight/hotel discovery. | Strong counterevidence to an “unserved Indian rewards market” claim. Whole-trip allocation may still differentiate, but requires a direct task comparison. [Official site](https://savesage.club/), [Developer's Play Store listing](https://play.google.com/store/apps/details?id=com.savesage.club) |
| **point.me / Amex point.me** | Transfer-partner award-flight search and booking guidance. The dedicated Amex experience is described as available for eligible **US-issued** cards. | Amex already recognizes and addresses award-search friction. Issuer-country-specific rules may be a useful segment boundary, but never assume US Amex transfer rules apply to India-issued cards. [Amex overview](https://connect.point.me/help/american-express-point.me-for-membership-rewards-overview), [Supported card programs](https://connect.point.me/help/which-credit-card-reward-programs-does-the-point.me-search-tool-support) |
| **PointsYeah** | Flight and hotel award search, cash/points comparisons for hotels, discovery and alerts. | “Flights plus hotels plus points” already exists. Public speed and usage numbers are marketing claims, not independently comparable benchmarks. [Product](https://www.pointsyeah.com/landing), [Hotel search guide](https://www.pointsyeah.com/insider/product/search-award-hotels) |
| **seats.aero** | Cached/live award discovery and a browser extension comparing cash fares with points results. Its docs explicitly distinguish cached coverage from live support and require airline confirmation before transferring. | Freshness labels and verify-before-transfer are valuable but not unique. API access is a separate issue: the documented live-search API requires a commercial agreement; a consumer Pro account is not equivalent. [Search semantics](https://docs.seats.aero/article/47-why-are-my-search-results-empty-or-missing-airlines), [Extension](https://docs.seats.aero/article/97-seatsaero-browser-extension-faq), [Live API](https://developers.seats.aero/reference/live-search) |
| **Roame** | Award discovery with card-program transfer guidance; documentation says its transfer instructions are currently tailored to US programs while airline searches serve international users. | Localized transfer instructions are a possible advantage, not proof of an empty market. [International support](https://help.roame.travel/articles/880052-do-you-offer-roame-in-my-country) |
| **CardPointers / MaxRewards** | Best-card recommendations, offers and benefits management. CardPointers also advertises AI/MCP integration; MaxRewards announced a web beta in August 2026. | “Which card should I use?” and “AI understands my wallet” are established features. Your proposed distinction is allocation across an entire planned trip with shared constraints and a traceable decision. [CardPointers features](https://cardpointers.com/pro/), [MaxRewards product](https://maxrewards.com/), [Changelog](https://feedback.maxrewards.co/changelog) |
| **Wanderlog / Mindtrip** | Wanderlog combines itinerary/map planning, collaboration, reservations, budgeting and expenses. Mindtrip announced its conversational Stays product in July 2026 following Flights. | An attractive itinerary, map and budget are baseline competitive capabilities. Rewards-aware decisions need to make the actual journey better. [Wanderlog](https://wanderlog.com/), [Mindtrip's announcement](https://www.prnewswire.com/news-releases/mindtrip-launches-mindtrip-stays-bringing-agentic-ai-to-hotel-search-and-booking-302826228.html) |

## 3. A credible USP, and its limits

### Proposed user promise

**“Make the most of the cards and points you already have, for the trip you actually want.”**

Supporting explanation:

**“Compare payment and redemption choices across your trip, see cash due now separately from estimated rewards value, and inspect the rules and evidence behind each recommendation.”**

The potentially differentiated bundle is:

1. **Trip first, existing wallet first.** Start from dates, people and preferences; do not force the user to start from buying another card or finding a spectacular premium-cabin redemption.
2. **Cross-purchase allocation.** A card that looks best for the next purchase may consume a shared reward cap better used later. This is a coupled allocation problem, not just multiplying each card's headline rate by each expense.
3. **Separate cash from valued rewards.** Deferred points value is not a reduction in the amount charged today. Explain valuation assumptions and surface their uncertainty.
4. **Auditable decisions.** Show the selected card/channel/offer, cap effects, runner-up where supported, transfer conditions, and evidence/trust state.
5. **Keep the trip editable.** Changing a stay or activity should update the payment consequences and identify any advice that needs rechecking.

This is a **candidate market position**, not a verified exclusive feature set. The reviewed pages do not establish whether competitors implement equivalent trip-wide shared-cap allocation internally. Establishing a practical advantage requires comparing the same real tasks in their products.

### What is real in this checkout

The payment kernel implements regret-ordered greedy allocation with a bounded pairwise improvement sweep, deterministic tie-breaking, shared cap state, and offer-use constraints. It is a heuristic. It is **not a proof of global optimality**, and the wider product is not a single joint optimizer over all possible itineraries, inventory, cards and redemptions. See [allocation](../backend/core/optimizer/allocate.py), [rules](../backend/core/optimizer/rules.py), and [offers](../backend/core/optimizer/offers.py).

The transfer pathfinder enumerates allowed one- and two-hop paths, performs backward integer source-requirement calculations, and evaluates timing, fees, balances and dominance. Describe that accurately; do not call it an arbitrary-hop graph optimizer or claim that a transfer path proves award availability. See [pathfinder](../backend/core/transfer/pathfinder.py) and [arithmetic](../backend/core/transfer/arithmetic.py).

Editable itinerary/recompute behavior and provenance rendering exist. The current-state documentation still describes mock-first frontend behavior and incomplete account/planning-flow wiring. CP1 is a domain and persistence foundation, not evidence that a resumable conversational product is already deployed. See [current state](../docs/CURRENT_STATE.md) and [planning repository](../backend/planning/repository.py).

The latest Gondola report is especially important: successful read-only searches returned Markdown inside `result: string`, not the typed inventory arrays assumed by synthetic fixtures. Missing semantics prevent admission as complete flight/hotel quotes; product activation remains pending. A live tool returning a result is not equivalent to a verified, usable recommendation. See [14 October contract probe](gondola_response_contract_probe_2026_10_14.md).

The explainer grounding check validates recognized rupee strings against computed values. That is useful protection, but does not prove all prose claims, units, causal explanations or associations are correct. An allowed number can be attached to the wrong claim. See [grounding implementation](../backend/agents/explainer.py).

### What could become defensible

A well-maintained issuer-country-specific rule set, a difficult edge-case corpus, evidence lineage, trustworthy comparison behavior, and consented outcome feedback could become durable assets. None is automatically a moat. Competitors can reproduce UI and algorithms; financial-data maintenance and distribution remain substantial work. There is no demonstrated network effect in the reviewed product evidence.

## 4. Product-market-fit hypothesis and a zero-cost validation plan

### Initial segment

Start with Indian residents who already own multiple rewards cards or transferable balances and have a concrete international leisure trip to plan. Use **India → Singapore** as the first evaluation corridor because it is the implemented kernel corridor. Do not expand to a new country just for a more appealing landing page before the first trip is credible.

The task to validate:

> “For this trip, help me decide where my existing cards and points are actually useful, without spending an evening reconciling travel sites, card terms and redemption guides.”

Potential mismatches: casual single-card travelers may not save enough to justify setup; experienced award hunters may value broad inventory and speed over itinerary help; groups may care more about coordination; infrequent travelers may not justify subscriptions. These are hypotheses to test, not established customer findings.

### Evidence of a category problem

Expedia's April 2026 research, commissioned from YouGov across more than 5,700 adults in the US, UK and India, reports interest in AI planning but much greater preference for trusted brands at booking. This supports testing control, verification and accountable evidence. It does **not** establish demand for TripPlanner, Indian multi-card users specifically, or willingness to pay. The sponsor has an interest in trusted-booking-brand positioning. [Survey and methodology](https://ir.expediagroup.com/news-and-events/news/news-details/2026/Expedia-Group-Reveals-The-AI-Trust-Gap-Travelers-Embrace-AI-for-Planning-but-Rely-on-Trusted-Brands-to-Book/default.aspx).

The presence of SaveSage and award-search businesses indicates active supply addressing related problems. It does not establish your differentiation or business economics.

### Proposed research sequence

These are **suggested pilot sizes and decision criteria**, not measured results, industry standards or statistical proof of PMF.

1. **Fifteen discovery interviews.** Recruit a mix of rewards beginners, intermediate users and enthusiasts. Ask them to reconstruct their last actual trip: tabs used, steps taken, mistakes, unresolved decisions and time spent. Ask for concrete past behavior before describing the product. Do not ask “Would you use an AI travel planner?”
2. **Ten observed task comparisons.** Use a real upcoming or recently completed trip. Compare the participant's normal workflow with TripPlanner. Counterbalance order where practical and use an equivalent comparison task to reduce learning effects. Compare with SaveSage/rewards tools when participants already use them; do not purchase access or assume inaccessible competitor capabilities are absent.
3. **Independent result verification.** Have the participant verify the exact trip, passengers, fare/room/cancellation conditions, card eligibility, dates and fees at the relevant first-party source. Keep valuation-derived gains separate from cash reductions. Treat manual evidence as manual; never relabel it live.
4. **Follow the decision outcome.** Did they change a card/channel/redemption decision? Did they actually use the recommendation? When their next eligible trip arises, do they return or refer another traveler? Travel is episodic, so weekly retention can mislead.

Candidate early go/no-go signals: most observed users finish without explanation from the builder; several can name a verified decision they improved; setup effort is smaller than the effort saved; and some take a meaningful action such as verifying a recommendation, sharing a real trip brief, or returning with another trip. For a small pilot, report counts and examples rather than presenting precise population estimates.

### Metrics worth recording

| Metric | Operational definition | Why it matters |
|---|---|---|
| Activation | A traveler supplies a usable wallet and trip, receives a report, and can correctly explain one recommended decision. | An account signup or a rendered plan alone does not show value. |
| Time to useful decision | Time from starting the task to identifying a usable, correctly understood recommendation; also record wallet-setup time. | Measures whether aggregation earns its complexity. |
| Verified decision gain | Difference from the user's feasible baseline on comparable evidence, computed by deterministic code; cash and valuation-derived benefits reported separately. | Prevents overstated savings. |
| Evidence coverage | Fraction of relevant recommendations supported by sufficiently complete, in-window evidence, with missing domains explicit. | Exposes the live-inventory bottleneck. |
| Verification survival | Whether the recommendation remains feasible and advantageous after first-party checking; record failures and missing data. | More useful than a screenshot of an impressive redemption. |
| Trust comprehension | Can the user distinguish cash-now, deferred rewards value, estimate, cache and current quote? | A beautiful interface can still mislead. |
| Return on next eligible trip | Repeat usage among users who actually have another relevant trip. | Matches the cadence of the problem. |

### Priority recommendation

Close one coherent corridor journey: account/wallet product wiring, confirmed brief, admissible evidence or an honest manual/fixture path, deterministic comparison, editable result, and verification. This is guidance for choosing the next approved milestone, not authorization to bypass the existing sequence or duplicate work in other branches.

Avoid broad country expansion, new-card acquisition, a browser extension, more agent roles or another integration before demonstrating a useful trip decision. The current non-commercial USD-0 profile remains appropriate for a portfolio and local pilot. Commercial PMF would additionally require sustainable evidence access and operating economics; those questions should be revisited only if commercialization becomes an actual goal.

## 5. Research papers and how to use them

These papers mostly study planning and evaluation, not Indian credit-card reward correctness. They do not validate financial rules, award availability or commercial reuse rights. Adapt methods first; inspect code/data licences and source restrictions separately before importing artifacts.

| Work | Useful contribution | Application and limits |
|---|---|---|
| **TravelPlanner**, Xie et al., **ICML 2024** | A sandbox benchmark combining travel information gathering and multi-constraint planning. | Adopt separate delivery, constraint and full-plan success measurements. The paper's much-cited 0.6% result describes a historical setup, not current frontier-model performance. Its US-oriented sandbox is not a live travel source. [Publication](https://proceedings.mlr.press/v235/xie24j.html) |
| **Large Language Models Can Solve Real-World Planning Rigorously with Formal Verification Tools**, Hao et al., 2024 preprint, revised 2025 | Combines language interaction with SMT constraint solving and uses unsatisfiable cores to guide repair. | Explore typed hard constraints and explicit conflict explanations: which requirement must change? Keep solver construction code-owned; do not adopt arbitrary generated-code execution. Solver guarantees concern the encoded problem, not truthful extraction or fresh data. Runtime limitations make offline experiments preferable initially. [Paper](https://arxiv.org/abs/2404.11891) |
| **TripCraft**, Chaudhuri et al., **ACL 2025** | Evaluates temporal, spatial, ordering and persona quality with more realistic trip context. | Add replay evaluations for meal timing, venue hours, visit duration, route order and traveler pace. Current date-level closure checks and conservative distance estimates are useful but not a full transit/timetable model. TripCraft also cautions that high planning scores can hide omitted constraints. [Publication](https://aclanthology.org/2025.acl-long.834/) |
| **Beyond Itinerary Planning / TravelBench**, Cheng et al., **ACL 2026** | Separates single-turn, multi-turn and unsolvable travel tasks with reproducible cached tool behavior. | Particularly relevant to CP2/CP3: evaluate when to answer, ask a useful question, or admit a missing capability. Reuse your recording/replay pattern; measure unnecessary questions and incorrect assertions of feasibility. [Publication](https://aclanthology.org/2026.acl-long.1347/) |
| **TravelEval**, Chen et al., 2026; arXiv record reports **KDD 2026 acceptance** | Six-dimensional evaluation spanning accuracy, compliance, time, space, economy and utility. | Build a scorecard beyond a single LLM-judge score and evaluate the whole trip. Use existing local/open/reference inputs; the paper's API-backed setup is not a requirement to activate paid routing. [Paper](https://arxiv.org/abs/2606.01046) |
| **UTP-Bench**, Rao et al., September 2026; arXiv record lists **EMNLP 2026** | India-focused evaluation of temporal buffers, crowd-aware timing and delay absorption. | Later, stress replayed plans with deterministic delay scenarios and report whether they remain feasible. Historical India data does not establish real-time delay prediction or transfer to Singapore. [Paper](https://arxiv.org/abs/2609.02421) |
| **A systematic literature review for the tourist trip design problem: Extensions, solution techniques and future research lines**, 2022 | Connects itinerary design to orienteering and related constrained routing problems, covering multiple objectives and uncertainty. | Use the taxonomy to specify routing constraints and choose baselines. The repo already contains an OR-Tools composer: audit and benchmark it before proposing a replacement. An itinerary-routing solver is separate from the frozen payment-allocation algorithm. [Review](https://doi.org/10.1016/j.orp.2022.100228) |

### Highest-value research experiment

Build an **offline benchmark of trip-and-wallet decisions under incomplete evidence**. This is a proposed project, not an implemented feature or a novelty claim.

- Compare the current payment heuristic with a naive per-line best-card baseline and a bounded exhaustive oracle on small instances. Include the same offer/cap/rounding semantics in every baseline; independently validate the oracle. Measure objective gap and constraint violations. Keep the oracle out of runtime and preserve all frozen goldens.
- Evaluate a direct-LLM baseline versus the existing governed pipeline on a held-out replay corpus. Disclose available information, model/version, prompt, retries, call ceilings, hardware and inclusion of fallback time.
- Include stale rules, absent fees, changing inventory, insufficient balances, exhausted shared caps, repeated requests, unsupported dimensions and contradictory requirements.
- Measure feasibility, verified arithmetic, unsupported claims, appropriately refused/qualified answers, call count, and p50/p95 latency. Report completion coverage with quality; a system can appear safe by refusing everything.
- Use real user tasks when consented and available. Until then, label synthetic/replayed evidence explicitly. Do not claim an official TravelPlanner or TravelBench score from a modified task or evaluator.

The scientific question is whether bounded, deterministic decisions improve correctness and decision usefulness without excessive setup, refusal or latency. It is stronger than simply adding an agent framework. It is also compatible with the repo's current architecture: no runtime optimizer replacement, no new unapproved call sites, no paid provider requirement.

## 6. What would impress a senior Expedia or Amex engineer?

My assessment: **yes, this can be an impressive portfolio project**, particularly for early-career backend, applied-AI or platform roles. It will not by itself demonstrate staff-level organizational impact or operation at Expedia/Amex scale.

An Expedia-oriented discussion can emphasize inventory semantics, freshness, provider failure, comparable quotes, itinerary feasibility and reproducible end-to-end behavior. An Amex-oriented discussion can emphasize financial arithmetic, shared caps, reward eligibility, explainability, session/privacy boundaries and rule approval. These are inferred relevance areas, not promises about either company's hiring rubric.

### Strong existing evidence

| Technical story | Evidence in the repository | Useful interview question |
|---|---|---|
| Integer financial semantics and cap-aware allocation | `backend/core/optimizer/{money,rules,offers,allocate}.py`, optimizer goldens | Why can a locally attractive card choice hurt later purchases? How do rounding, cap fall-through and offer order interact? |
| Transfer planning with discontinuities | `backend/core/transfer/{arithmetic,pathfinder}.py`, transfer goldens | Why must required source units be computed backward, and why is ordinary exchange-rate multiplication insufficient? |
| Governed language workflows | `backend/agents/`, recording/replay and scenario evaluations | What is deterministic? How do you detect failure? What is the fallback, and what can the grounding check miss? |
| Session consistency | `backend/planning/repository.py`, `backend/accounts/store.py`, CP1 concurrency/idempotency tests | How do you prevent lost updates and handle duplicate client events? Why is this not a global exactly-once guarantee? |
| Provider security and evidence admission | Gondola allowlist/OAuth/budget tests and October contract probe | How did you prevent scope escalation? Why reject successful search results that look plausible? |

### Résumé bullet drafts grounded in inspected code

Use only the bullets corresponding to work you actually owned and can explain; replace “implemented” with the accurate contribution verb if ownership was shared or assistance was substantial.

- **Implemented a deterministic Python rewards allocator using integer money arithmetic, shared-cap accounting, regret-ordered allocation and bounded pairwise improvement to generate explainable card/offer assignments across trip expenses.**
- **Built a one- and two-hop loyalty-transfer planner with backward integer rounding, transfer minimums/increments, bonus and fee modeling, balance checks and Pareto filtering.**
- **Separated typed LLM planning and explanation from financial computation; added recording/replay evaluations, bounded calls, deterministic fallbacks and rejection of ungrounded rupee amounts.**
- **Implemented user-scoped SQLite planning-session persistence with compare-and-swap version checks and client-event idempotency, supporting reproducible confirmed trip briefs.**

An integration-focused alternative, if it reflects your contribution:

- **Hardened a read-only MCP travel adapter with tool allowlisting, OAuth scope checks, persistent call budgets and circuit breaking; diagnosed live-versus-fixture contract drift and prevented incomplete search evidence from entering quote-based optimization.**

These are technical bullets without fabricated performance numbers. Add measured impact later: objective gap versus baseline, p95 recompute latency at a stated input size, verification survival, or user task-time reduction. Existing milestone test counts are historical evidence; do not present them as a fresh measurement or make test quantity the primary accomplishment.

### The demo and evidence package

Prepare one short, replayable corridor demo:

1. Enter a real-shaped wallet and trip, with evidence mode visible.
2. Show a shared-cap case where independent per-purchase ranking makes a worse choice.
3. Explain one cash/points decision, including fees, valuation assumptions, transfer increment and verify-before-transfer.
4. Edit the itinerary and show recomputation and stale-section behavior.
5. Simulate a provider failure or incomplete quote and show the honest partial result.

Pair it with a small benchmark report, architecture diagram, one worked arithmetic example generated by the kernel, and a concise failure postmortem. The Gondola contract mismatch is a strong systems lesson because it distinguishes transport success from semantic correctness.

Claims to avoid: globally optimal trip planning; production-scale financial infrastructure; fully live award availability; formally verified end-to-end behavior; zero hallucinations; universal coverage; and a public PMF conclusion unsupported by observed users. None is required for a strong portfolio.

## Recommendation

Make the next unit of progress **one demonstrably better, understandable trip decision**. Complete the relevant approved product wiring, establish a credible evidence path, compare against realistic alternatives, and publish reproducible technical measurements. That work strengthens both the product hypothesis and the résumé more than a larger feature list.

No product code, authoritative spec, seed fact, provider activation or existing user file was changed by this research. This report is the sole added artifact.
