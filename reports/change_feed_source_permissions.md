# Change feed and real data: source permissions (recommendations, not policies)

**Status:** recommendations for the owner. This report creates no source policy, watch target, alias or fetch, and approves nothing. It is a reading of public pages, not legal advice.
**Author:** Opus (design). **Date:** 2026-11-12.
**Inputs read:**
- Kiro's research `docs/research/change_feed_source_facts.md`: PR #41, branch `codex/change-feed-source-facts`, head verified `71f09496b4d97fdfebf845f2606fdcf7229a0900`.
- The owner-decision record `reports/card_bank_source_permissions.md`: branch `claude/card-source-permissions` `2612e43`, §5A, not on `main`.
- Flash's Firecrawl report `reports/firecrawl_ingestion.md`: branch `codex/firecrawl-ingestion` `15ec9eb`, not on `main`.
- Sol's change-feed design (`codex/sol-feed-concurrency-design` `6adf7ae`) §3–4.
- Spec 05.

## 1. Three separate permissions

A source can be allowed for one of these and not the others. No row below lets one stand in for another.

| Permission | Question | Governed by |
|---|---|---|
| **Fetch** | May an automated agent read the page? | robots.txt for *that agent's* user-agent token, the site terms, spec 05 (honest UA, ≥ 10 s per domain, stop on block) |
| **Store** | May the project keep numbers and short quoted evidence from it in a local KB? | Site terms (copying, "enter into a database") and the owner's 2026-11-01 local-only decision |
| **Display** | May the deployed site or the public repository show values, summaries or links from it? | Site terms (publish, redistribute, commercial). **No owner decision covers this yet for any source** |

robots.txt answers only the fetch question. The terms answer store and display. Sol's change-feed design already states the same: "fetch permission alone is not redistribution permission".

## 2. Recommendations at a glance

| Source | Fetch | Store (local KB) | Display (site/repo) | Already decided by the owner |
|---|---|---|---|---|
| HDFC Bank `hdfc.bank.in` | **manual_only** (see §3.1: Firecrawl's agent is disallowed) | allowed under the 2026-11-01 local-only decision | **not decided** | automation approved in principle (5A); local-only store |
| Axis Bank `axis.bank.in` | **automated** for HTML `card_page` / `offer_page`; PDFs manual capture or the local PDF worker | allowed (local-only) | **not decided** | automation approved (5A); one live Firecrawl call authorized 2026-11-07 |
| SBI Card `sbicard.com` | automated (not needed for the first slice) | allowed (local-only) | **not decided** | automation approved (5A) |
| ICICI Bank `icici.bank.in` | **manual_only** (HTML automation not approved; robots disallows `*.pdf`) | allowed (local-only) | **not decided** | local-only store; HTML automation open (Q3) |
| Singapore Airlines KrisFlyer `singaporeair.com` | **do_not_use** for automation | **do_not_use until the owner reads the terms** | **do_not_use** | nothing |
| Air India loyalty `airindia.com` | **do_not_use** | **do_not_use** (see §3.6) | **do_not_use** | nothing |
| The Points Guy `thepointsguy.com` | **do_not_use** for automation | **lead only, manual**: "a promotion may exist" plus the primary URL; no values, dates or text | **do_not_use** | nothing |
| CardExpert, BankBazaar (earlier record) | manual_only | lead only (card name + issuer URL) | do_not_use | manual lead use approved (5A) |
| Paisabazaar (earlier record) | do_not_use | do_not_use | do_not_use | unused |

"Automated" here means only that the recorded robots rule and the clauses found do not forbid it. It activates nothing. Every automated fetch still needs an enabled policy record created by the owner and, for Firecrawl, the per-call owner authorization and credit controls on Flash's branch.

## 3. Source by source

Quotations are short excerpts from Kiro's research, checked against it. They are not full terms.

### 3.1 HDFC Bank (`hdfc.bank.in`)
- **robots:** `User-agent: *` → `Allow: /`. It also fully disallows about 135 named agents in separate groups, including the default agents of `Python-urllib` and `Wget` (Kiro; earlier record). Flash's Firecrawl report records **`Disallow: /` applying to its target** and refused HDFC before dispatch.
- **Terms:** the user agrees not to "copy, reproduce … enter into a database …", "except that which I may download for my own personal, non-commercial use" (https://www.hdfc.bank.in/useful-links/website-usage-terms, read 2026-11-11).
- **Ambiguity:**
  - A local research KB *is* a database. The owner's 2026-11-01 decision accepted it as personal, non-commercial and local-only, so it stands only while the KB stays local and unpublished.
  - The 5A automation approval assumed an honest custom user agent that robots allows. The only automated backend that exists is Firecrawl, and its agent is disallowed.
- **Recommendation:**
  - Fetch: manual capture in the owner's browser, saved locally, staged with `--captured-at`. Do not use Firecrawl for HDFC.
  - A direct fetcher with its own honest UA would be a new capability (prerequisite P-6 in the rollout spec). Only build it if the owner wants HDFC automated.
  - Display: undecided.

### 3.2 Axis Bank (`axis.bank.in`)
- **robots:** `User-agent: *` → `Allow: /`, with `Disallow: /Sitefinity/` and one unrelated PDF. It also disallows about 135 named agents.
- **Terms:** copyright notice ("is owned by Axis Bank Limited"). **No clause on automated access, copying or databases was found** (keyword search, https://www.axis.bank.in/disclaimer, 2026-11-11).
- **Prior action:** the owner authorized one live Firecrawl `/v2/scrape` of the Atlas card page on 2026-11-07, under policy `axis-bank-in-firecrawl-card-page-v1`. Its extraction was curator-authored, not model output.
- **Ambiguity:**
  - An absent clause is not a grant. The keyword search could miss differently worded text.
  - Copyright still covers display of page text.
- **Recommendation:**
  - Fetch: automated for HTML `card_page` / `offer_page` through the existing Firecrawl controls, each run owner-authorized.
  - `tnc_pdf`: manual capture plus the local `pdfplumber` worker. Firecrawl admits only HTML.
  - Store: numbers plus short quotes, locally.
  - Display: undecided.

### 3.3 SBI Card (`sbicard.com`)
- **robots:** `Allow: /*`, `Disallow: /en/webform/*`.
- **Terms:** view or download "only for your personal, non-commercial use". There is no right "to copy, reproduce … enter into a database". (Usage agreement URL in Kiro §3.3.)
- **Recommendation:** automated is permitted by 5A but not needed for the first slice. Store and display are as for HDFC.

### 3.4 ICICI Bank (`icici.bank.in`)
- **robots:** `Disallow: *.pdf`, `*.xls`, `*.doc`, `*.docx`, `*.jpg`, `/ajax/*` and more. HTML card pages are not disallowed.
- **Terms:** download "for noncommercial, personal use only". Use "for public or commercial purposes" needs written permission (https://www.icici.bank.in/disclaimer).
- **Recommendation:**
  - Fetch: manual_only for everything until the owner answers Q3. PDFs stay manual even after that, because robots binds automated agents only.
  - Not in the first slice.

### 3.5 Singapore Airlines KrisFlyer (`singaporeair.com`)
- **What was retrieved:** nothing. robots.txt, the homepage and the conditions-of-use page all returned the WAF deny page (HTTP 404 "SIA-Maintenance Page") to an honest user agent. Kiro correctly stopped.
- **Provenance gap:** Kiro's §3.5 nonetheless quotes "published Conditions of Use", for example "You may not reproduce, republish … without the prior written permission of SIA". It also adds an unsourced paraphrase about a developer portal. **There is no retrieval record for these quotes, so this report does not rely on them.**
- **Recommendation:**
  - Fetch: do_not_use for automation. A deny page to an honest agent is a block, and spec 05 says stop.
  - Store and display: do_not_use until the owner reads the conditions of use in a browser and records URL, date and clauses.
  - Where an issuer's own pages state a transfer relationship (bank currency → KrisFlyer), that evidence comes from the issuer, not from this site. Whether they do is checked at capture time, not assumed. This site is needed for **award prices**, which are therefore deferred.

### 3.6 Air India loyalty programme (`airindia.com`)
- **What was retrieved:** nothing (connection dropped at 15 s for every URL).
- **Provenance gap:** as with Singapore Airlines, Kiro quotes terms without a retrieval record. The quoted clause, if accurate, bars monitoring or copying "using any robot, spider, scraper or other automated means **or any manual process**" without written permission. That would forbid even manual capture.
- **Recommendation:** do_not_use for fetch, store and display. The owner may read the terms in a browser. If that clause is confirmed, the source stays unused unless written permission is obtained.

### 3.7 The Points Guy (`thepointsguy.com`) — aggregator
- **robots:** editorial pages are not disallowed for `*`. `/api/`, `/apply/`, `/search/`, `/feed/` and `/rss/` are.
- **Terms:**
  - They forbid "any robot, spider, scraper … to 'scrape', access, acquire, copy, or monitor" without written permission, with an exception for "public search engine operators".
  - They forbid copying or compiling content without permission.
  - They state "The Services we provide Users are for personal use only" (https://thepointsguy.com/legal/terms-of-use).
- **Spec 05:** an aggregator value can never become a stored fact.
- **Recommendation:**
  - Fetch: do_not_use for automation. The robots allowance is overridden by the terms, and the RSS feed is disallowed too.
  - Store: the owner may read it as any visitor does and record only a lead: subject names ("Axis → KrisFlyer"), "a promotion may exist", and the primary (issuer or programme) URL. No numbers, dates or text.
  - Display: never a publication source. A feed event needs a permitted primary capture (Sol §3 `primary_confirmed`).

## 4. Owner decisions (precise)

1. **Display permission (blocks every public use of real data).** For each issuer you intend to show (HDFC, Axis first), decide whether the deployed site may show issuer-derived **numbers** with a source link. Repository publication is a separate yes or no. The local-only decision of 2026-11-01 does not cover either. If yes for anything public, record the basis, for example counsel's view or written permission. Until then, real data stays in a private seeds directory and the deployed site stays on placeholder data (rollout spec §5).
2. **HDFC fetch path.** Accept manual capture as the only HDFC path, or approve building a direct honest-UA fetcher (P-6). Firecrawl is refused by robots either way.
3. **Axis policy records.** Create and attest the `card_page` HTML policy for Firecrawl (one exists from the pilot) and a manual `tnc_pdf` policy. This report proposes values only.
4. **ICICI Q3:** HTML automation yes or no. PDFs stay manual.
5. **KrisFlyer and Air India:** read the conditions in your browser and record URL, date and the clauses on copying and automation. Until then both are do_not_use, and the award-price slice waits.
6. **The Points Guy:** approve manual lead-only use as defined in §3.7, or drop it.
7. **Rate and identity:** keep spec 05's ≥ 10 s per domain and an honest custom user agent for any future direct fetcher. No source states a numeric limit.
