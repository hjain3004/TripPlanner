# Card data bank: source permissions (Phase 1)

**Status:** research record for owner approval. Nothing here activates a source.
**Plan:** `docs/superpowers/plans/2026-10-31-indian-card-data-bank.md` (branch `claude/card-data-bank-plan`, `0900d41`), Phase 1.
**Date read:** 2026-11-01 (UTC). **Base:** `origin/main` `8d805e3`.
**Governing rules:** spec 05 (terms-of-service gate; aggregator values are leads only; robots.txt, at least 10 s per domain, honest user agent) and the plan's source rule.

This is a reading of public terms and `robots.txt`, not legal advice. Where a clause is
ambiguous the report says so and leaves the decision to the owner.

## 1. Verdicts at a glance

| Source | Role | Terms verdict | robots.txt verdict (general agents) | Recommended policy |
|---|---|---|---|---|
| `cardexpert.in` | discovery lead | Forbids automated access and copying without written permission | Allows all except `/wp-admin/` | **manual_only**, lead facts only |
| `paisabazaar.com` | discovery lead | **Not read: blocked** | **Not read: blocked** (HTTP 403 on `robots.txt` itself) | **do not use** until a human reads its terms |
| `bankbazaar.com` | discovery lead | Forbids robots and manual copying or monitoring; personal, non-commercial | Allows content; disallows many app and lead endpoints | **manual_only**, lead facts only (lowest priority) |
| `hdfc.bank.in` | issuer | Personal, non-commercial, local-only (from the plan; **not re-read today**) | Allows all except `/homeloans-cug` | automated allowed (HTML and PDF), local-only |
| `axis.bank.in` | issuer | Copyright and liability terms; no automation or copying clause found | Allows all except `/Sitefinity/` and one unrelated PDF | automated allowed (HTML and PDF), local-only |
| `sbicard.com` | issuer | Personal, non-commercial; no automation clause found | Allows all except `/en/webform/*` | automated allowed (HTML and PDF), local-only |
| `icici.bank.in` | issuer | Personal, noncommercial; reuse barred without permission | **Disallows `*.pdf`** (and `.xls`, `.doc`, `.docx`, `.jpg`) | HTML automated allowed; **PDFs manual_only** |

"Automated allowed" means robots and the clauses found do not forbid it. It does not turn
anything on, and Phase 2 still starts from manual captures. No source states a numeric rate
limit; spec 05's 10 s per domain applies everywhere.

## 2. How this was read

- One plain HTTP read per page with `curl`, user agent
  `TripWise-source-permissions-research/1.0 (student project; reads public terms and robots.txt only)`,
  at least 11 s between reads, no retries, no login, no cookies, no JavaScript execution.
- Pages read: each `robots.txt`, each homepage (to find footer links), each terms page, each
  issuer sitemap named in its `robots.txt`, and each seeded card's product page. **No PDF was fetched.**
- Long pages were searched by keyword (automated, robot, spider, scrape, copy, reproduce,
  database, commercial, personal use) and the matching passages read in context. They were not
  read line by line, and a clause worded without those terms could be missed.
- Page text is not stored in the repository. For audit, the first 16 hex characters of the
  SHA-256 of each file as read: CardExpert terms `18bb8d865eeb7ab2`, BankBazaar terms
  `ad74872d9d1cf475`, Axis disclaimer `1c7f999c4fc35d4a`, SBI Card usage agreement
  `dd235260056fc4a1`, SBI Card disclaimer `d70a45c9cf5c571c`, ICICI disclaimer
  `9e182e0ad5fe2a37`; `robots.txt`: CardExpert `0ee169ed89d6bab4`, BankBazaar
  `a4aa73162de5153d`, HDFC `d0b72cc34687c3cc`, Axis `9d2cc2b11c1e49a9`, SBI Card
  `aff462c12f0d4486`, ICICI `975397fb87ae0b80`.
- **One block:** Paisabazaar answered with an Akamai "Access Denied" (HTTP 403) to the
  `robots.txt` request itself. Per the brief I stopped there, did not retry, and did not try
  another route.

## 3. Discovery aggregators (leads only)

Spec 05: an aggregator value can never become a stored fact. A lead may carry only "this card
exists" and the issuer URL it points to.

### CardExpert: `www.cardexpert.in`
- **Terms:** https://www.cardexpert.in/terms-of-use/ (read 2026-11-01). Short page, read in full.
- **Automation:** forbidden without prior written permission, including a ban on bypassing robot exclusion headers.
  Quote: "robot, spider, scraper, deep link or other similar automated data gathering".
- **Copying:** content may not be copied, reproduced or republished without written permission.
  The site says its content is for informational purposes only.
- **robots.txt:** `User-agent: *` disallows only `/wp-admin/` (with `admin-ajax.php` allowed); lists sitemaps. robots allows what the terms forbid, so the terms govern.
- **Rate limit:** none stated beyond a general ban on unreasonable load.
- **Recommendation: manual_only.** A human may read it as any visitor does. Record only the card name and the issuer's URL; store no page text, ratings or numbers.

### Paisabazaar: `www.paisabazaar.com`
- **Terms:** not read. **robots.txt:** not read.
- **What happened:** `GET /robots.txt` returned HTTP 403 "Access Denied" from `AkamaiGHost`
  (reference `#18.6ea7cb17.1793518224.3b5dc53c`, 2026-11-01 07:30 UTC). Stopped for this site.
- **Recommendation: do not use**, because no terms record exists and spec 05 allows no
  source without one. If you want it as a lead source, read its terms in your own browser and
  tell me the URL, the date and the relevant clauses; I will not read it further.

### BankBazaar: `www.bankbazaar.com`
- **Terms:** https://www.bankbazaar.com/conditionsofuse.html (read 2026-11-01), footer link "Terms".
- **Automation and copying:** bars robots and also manual copying or monitoring; licence is personal and non-commercial use.
  Quote: "robot, spider, other automatic device, or manual process to monitor or copy".
  It also states there is no right to download or copy the Services, and bars selling its information.
- **robots.txt:** `User-agent: *` allows content pages but disallows 95 app, lead and
  account paths, among them `*/card-details.html` and `*/search.html`. It names GPTBot,
  ClaudeBot and PerplexityBot as allowed and CCBot and dotbot as disallowed.
- **Rate limit:** none stated.
- **Recommendation: manual_only, lowest priority.** The terms are stricter than CardExpert's
  (they reach manual copying). Use only for "this card exists, here is the issuer URL", or drop it.

## 4. Issuers of the four seeded cards

| Seeded card | Issuer | Current official domain | Legacy domain behaviour |
|---|---|---|---|
| `hdfc-infinia` | HDFC Bank | `www.hdfc.bank.in` | `hdfcbank.com` was bot-protected per the plan; not tested today |
| `axis-atlas` | Axis Bank | `www.axis.bank.in` | `axisbank.com` redirects to `axis.bank.in` (verified) |
| `sbi-cashback` | SBI Card | `www.sbicard.com` (no `.bank.in` move observed) | none observed |
| `icici-emeralde` | ICICI Bank | `www.icici.bank.in` | `icicibank.com` redirects to `icici.bank.in` (verified) |

### HDFC Bank: `hdfc.bank.in` (restated from the plan, robots re-checked)
- **Terms:** website usage terms read earlier per the plan; the content is personal,
  non-commercial and local-only per the owner's decision. **Not re-read on 2026-11-01.**
- **robots.txt (re-read today):** `User-agent: *` is `Allow: /` with `Disallow: /homeloans-cug`;
  explicit allow groups for named AI agents. No crawl delay. It also fully disallows 135 named agents,
  among them the default agents of `Wget`, `Python-urllib`, `httplib` and `lwp-trivial`.
- **Product page:** https://www.hdfc.bank.in/credit-cards/infinia-credit-card (read, HTTP 200, no block from `curl`).
- **Fees page:** https://www.hdfc.bank.in/credit-cards/infinia-credit-card/fees-and-charges (listed in the sitemap, not opened).
- **MITC PDF (linked from the product page):** https://www.hdfc.bank.in/content/dam/hdfcbankpws/in/en/personal-banking/discover-products/cards/credit-cards/personal-mitc/mitc-in-english.pdf. It is the personal-cards MITC, not Infinia-specific.
- **Card-specific PDF:** https://www.hdfc.bank.in/content/dam/hdfcbankpws/in/en/personal-banking/discover-products/cards/credit-cards/infinia-credit-card/rewards-points-program-terms-and-conditions.pdf (also lounge, golf, fuel and concierge T&Cs in the same folder).

### Axis Bank: `axis.bank.in`
- **Terms:** https://www.axis.bank.in/disclaimer (read 2026-11-01), the page that carries the site terms. `/terms-and-conditions` is offers T&C, not site use.
- **Clauses:** copyright, trademarks, as-is warranty and liability. It states the pages are copyright-owned
  by the bank ("is owned by Axis Bank Limited"). **No clause on automated access, copying or databases was found.** It tells visitors who disagree not to access the site.
- **robots.txt:** `User-agent: *` is `Allow: /` with `Disallow: /Sitefinity/` and one unrelated PDF (Primus card T&C). No crawl delay. Like HDFC, it fully
  disallows about 135 named agents, including the default agents of `Wget`, `Python-urllib`, `httplib` and `lwp-trivial`.
- **Product page:** https://www.axis.bank.in/cards/credit-card/axis-bank-atlas-credit-card (read, HTTP 200).
- **PDFs on the page (versioned `?sfvrsn=` tokens omitted):**
  https://www.axis.bank.in/docs/default-source/default-document-library/credit-cards/terms-and-conditions-atlas-credit-card.pdf and
  https://www.axis.bank.in/docs/default-source/default-document-library/credit-cards/terms-and-conditions-of-features-of-axis-bank-atlas-credit-card.pdf.
  **No MITC PDF or Atlas fee schedule was found on the page**; `https://www.axis.bank.in/fees-and-charges` is bank-wide.

### SBI Card: `sbicard.com`
- **Terms:** https://www.sbicard.com/sbi-card-en/assets/docs/html/personal/usage-agreement/src/index.html (read, keyword-searched).
  `/en/tnc.page` is cardholder T&C and `/en/disclaimer.page` is liability text; neither has site-use rules.
- **Clauses:** licence to view or download "only for your personal, non-commercial use"; reuse for public or commercial purposes needs written permission. **No automation clause found.**
- **robots.txt:** `User-agent: *` is `Allow: /` with `Disallow: /en/webform/*`; allows named AI crawlers; disallows `Bytespider` and `CCBot`. No crawl delay.
- **Product page:** https://www.sbicard.com/en/personal/credit-cards/cashback-sbi-card.html (the sitemap's `.page` URL redirected here).
- **MITC:** https://www.sbicard.com/en/most-important-terms-and-conditions.page (an HTML page, not a PDF).
- **Key Fact Statement PDF (generic):** https://www.sbicard.com/sbi-card-en/assets/docs/pdf/kfs/key-fact-statement.pdf. No Cashback-specific fee PDF was found.

### ICICI Bank: `icici.bank.in`
- **Terms:** https://www.icici.bank.in/disclaimer (read 2026-11-01). `/personal-banking/terms-conditions` was keyword-searched and had no site-use clause.
- **Clauses:** personal use only. Quote: "You may download material displayed on the Site for noncommercial, personal use only".
  Distributing, modifying, reusing or using contents for public or commercial purposes needs written permission. **No explicit automation clause found.**
- **robots.txt:** `User-agent: *` **disallows `*.pdf`**, `.xls`, `.doc`, `.docx`, `.jpg`, plus `/campaigns/`, `/ajax/*` and others. Card pages are not disallowed. No crawl delay. It also fully disallows about 136 named agents, including the
  default agents of `Wget`, `Python-urllib`, `httplib` and `lwp-trivial`.
- **Product page:** https://www.icici.bank.in/personal-banking/cards/credit-card/emeralde-private-metal-credit-card (read, HTTP 200). Its sitemap also lists `emeralde-credit-card` and `emirates-emeralde`; the seeded name matches the private-metal page.
- **Fees:** an anchored section on the same page (`#emeralde-private-metal-credit-card-fees-amp-charges`).
- **MITC PDF (generic cards MITC, link only, not fetched):** https://www.icici.bank.in/content/dam/icicibank/india/managed-assets/revamp-page-images/docs/pdf/mitc_cc.pdf. Because robots disallows PDFs, an automated agent must not fetch it, so it is a manual capture.

## 5. Proposed source-policy values (for approval; none created)

| Domain | `automated_access_permitted` | `manual_only` | `allowed_page_classes` | Terms URL |
|---|---|---|---|---|
| `cardexpert.in` | false | true | discovery lead only | `/terms-of-use/` |
| `bankbazaar.com` | false | true | discovery lead only | `/conditionsofuse.html` |
| `paisabazaar.com` | not recorded | not recorded | none | unread |
| `hdfc.bank.in` | true | false | `card_page`, `tnc_pdf` | per plan (re-read before activation) |
| `axis.bank.in` | true | false | `card_page`, `tnc_pdf` | `/disclaimer` |
| `sbicard.com` | true | false | `card_page`, `tnc_pdf` | usage agreement URL above |
| `icici.bank.in` | true for `card_page`; **false for `tnc_pdf`** | PDFs: true | `card_page`; `tnc_pdf` manual | `/disclaimer` |

`terms_read_on` is 2026-11-01 for every row read today; `reviewed_by` and `reviewed_on` stay
empty until you approve.

## 6. Open questions for you

1. **Personal, non-commercial, local-only.** Every issuer licence is personal or non-commercial
   and reserves public or commercial reuse. Do you accept a local-only research bank under that
   reading, with no captured text published and facts stored as numbers with quotes only as
   short evidence? (Counsel, if this ever leaves the student profile.)
2. **Automated fetching for issuers.** Robots and the clauses found allow it for HDFC, Axis
   and SBI Card. Do you want to approve automation now, or keep manual capture as the only path
   until Phase 5?
3. **ICICI PDFs.** robots disallows them for automated agents. Confirm they are manual captures
   from your own browser.
4. **CardExpert and BankBazaar.** Approve `manual_only` lead use (names and issuer URLs only),
   or drop them? Do you want me to draft a written-permission request to CardExpert?
5. **Paisabazaar.** Leave it unused, or will you read its terms in your browser?
6. **HDFC.** I restated its terms from the plan. Should I re-read them before activation?
7. **Axis Atlas fees and MITC.** No MITC or fee schedule was found on the product page. Is the
   features T&C PDF the document to cite, or do you have a better source?
8. **SBI Cashback fees.** The MITC page and generic Key Fact Statement are the only documents
   found. Are they acceptable evidence for fee fields?
9. **Rate limit and user agent.** No rate limit is stated anywhere. Keep spec 05's 10 s per domain?
   HDFC, Axis and ICICI disallow the default agents of common libraries, so a future fetcher
   must always send an honest custom user agent (spec 05 already requires one).
10. **Seeded ICICI card.** Confirm `icici-emeralde` means the Emeralde Private Metal page.

## 7. Not done

No capture, scraping, PDF fetch, account, spend or code. Terms were read as of 2026-11-01 and
can change. The brief's "automated discovery allowed" label for issuers is a recommendation
for approval, not an activation: no watch target, source policy or fetch exists.
