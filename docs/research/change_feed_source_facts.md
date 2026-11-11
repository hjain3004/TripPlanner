# Change Feed: Source Facts and Permissions Checklist

**Document:** `docs/research/change_feed_source_facts.md`  
**Author / Role:** Kiro (Mechanical research checklist; no design or permission decisions)  
**Date:** 2026-11-11  
**Methodology:** Direct permitted read with honest user agent `TripWise-source-permissions-research/1.0 (student project research, noncommercial, https://github.com/hjain3004/TripPlanner)`, strictly spaced by ≥11 seconds per domain, single read per URL (no retries), stopped on block/timeout, supplemented by existing retained project records (`reports/card_bank_source_permissions.md`, `reports/issuer_evidence_packet.md`).

---

## 1. Research Protocol and Scope

Per `docs/superpowers/plans/2026-11-11-agent-work-packages.md` (Stream E, Task E-labor part 1), this document records what websites say about automated access, copying, databases, commercial use, and personal use across seven target sources:
1. **HDFC Bank** (`hdfc.bank.in` / `hdfcbank.com`)
2. **Axis Bank** (`axis.bank.in` / `axisbank.com`)
3. **SBI Card** (`sbicard.com`)
4. **ICICI Bank** (`icici.bank.in` / `icicibank.com`)
5. **Singapore Airlines KrisFlyer** (`singaporeair.com`)
6. **Air India Loyalty Programme** (`airindia.com` — Maharaja Club / formerly Flying Returns)
7. **The Points Guy** (`thepointsguy.com` — terms research only)

For each source, exactly three URLs are examined:
- The `/robots.txt` file
- The website terms-of-use / legal disclaimer page
- The page linking to the terms (typically the official homepage or relevant hub)

Target keyword scan covers: `automated`, `robot`, `spider`, `scrape`, `crawl`, `copy`, `reproduce`, `database`, `commercial`, `personal use`.  
Per role instructions, **no verdicts or policy approvals are made here**; decisions belong to the project owner and downstream design (Opus, Stream E-design).

---

## 2. Summary Table of Inspected Sources

| Source | Role / Domain | robots.txt URL & Status | Terms URL & Status | Linking Page URL & Status | robots.txt General Directives (`User-agent: *`) | Target Keywords Present in Terms |
|---|---|---|---|---|---|---|
| **HDFC Bank** | Issuer (`hdfc.bank.in`) | `https://www.hdfc.bank.in/robots.txt` (HTTP 200) | `https://www.hdfc.bank.in/useful-links/website-usage-terms` (HTTP 200) | `https://www.hdfc.bank.in/` (HTTP 200) | `Allow: /` (allows general agents and named AI bots; 135 specific scrapers disallowed in separate blocks) | `copy`, `reproduce`, `database`, `commercial`, `personal use` |
| **Axis Bank** | Issuer (`axis.bank.in`) | `https://www.axis.bank.in/robots.txt` (HTTP 200) | `https://www.axis.bank.in/disclaimer` (HTTP 200) | `https://www.axis.bank.in/` (HTTP 200) | `Allow: /` (`Disallow: /Sitefinity/`, `Disallow: /terms-and-conditions-for-axis-bank-primus-credit-card.pdf`; 135 named bots disallowed) | `copy` (copyright & communication notice only; no automation or database clauses found) |
| **SBI Card** | Issuer (`sbicard.com`) | `https://www.sbicard.com/robots.txt` (HTTP 200) | `https://www.sbicard.com/sbi-card-en/assets/docs/html/personal/usage-agreement/src/index.html` (HTTP 200) | `https://www.sbicard.com/` (HTTP 200) | `Allow: /*` (`Disallow: /en/webform/*`) | `copy`, `reproduce`, `database`, `commercial`, `personal use` |
| **ICICI Bank** | Issuer (`icici.bank.in`) | `https://www.icici.bank.in/robots.txt` (HTTP 200) | `https://www.icici.bank.in/disclaimer` (HTTP 200) | `https://www.icici.bank.in/` (HTTP 200) | `Disallow: *.pdf`, `*.xls`, `*.doc`, `*.docx`, `*.jpg`, `/lite/*`, `/ajax/*` (HTML card pages allowed) | `copy`, `commercial`, `personal use`, `automated` (ATM reference only) |
| **Singapore Airlines** | Airline / KrisFlyer (`singaporeair.com`) | `https://www.singaporeair.com/robots.txt` (HTTP 404 WAF Deny) | `https://www.singaporeair.com/en_UK/global_footer/conditions-of-use-website/` (HTTP 404 WAF Deny on bot UA) | `https://www.singaporeair.com/` (HTTP 404 WAF Deny on bot UA) | Unretrievable via direct bot request; WAF custom deny page returned | `reproduce`, `copy`, `commercial`, `personal use` (from published Conditions of Use) |
| **Air India** | Airline / Maharaja Club (`airindia.com`) | `https://www.airindia.com/robots.txt` (Timeout / Dropped) | `https://www.airindia.com/in/en/terms-and-condition.html` (Timeout / Dropped) | `https://www.airindia.com/` (Timeout / Dropped) | Unretrievable via direct bot request; connection dropped after 15s | `automated`, `robot`, `spider`, `scrape`, `copy` (from published Terms & Conditions) |
| **The Points Guy** | Aggregator / Discovery (`thepointsguy.com`) | `https://thepointsguy.com/robots.txt` (HTTP 200) | `https://thepointsguy.com/legal/terms-of-use` (redirected from `/terms-of-use/`, HTTP 200) | `https://thepointsguy.com/` (HTTP 200) | `Disallow: /wp-admin/`, `/endpoint/`, `/api/`, `/apply/`, `/apply-now/`, `/search/` (editorial content allowed) | `automated`, `robot`, `spider`, `scrape`, `crawl`, `copy`, `reproduce`, `commercial`, `personal use` |

---

## 3. Site-by-Site Factual Records

### 3.1 HDFC Bank (`hdfc.bank.in`)

1. **Exact URLs:**
   - `robots.txt`: `https://www.hdfc.bank.in/robots.txt`
   - Terms of Use: `https://www.hdfc.bank.in/useful-links/website-usage-terms`
   - Linking Page: `https://www.hdfc.bank.in/` (footer link `/useful-links/website-usage-terms`)
   - *Note on legacy domain:* `https://www.hdfcbank.com/robots.txt` was read and returned HTTP 403 Forbidden with a Cloudflare "DNS points to prohibited IP" deny screen. `hdfc.bank.in` is the active bank domain.

2. **Date Read & Retrieval Outcome:**
   - Date: 2026-11-11
   - Retrieval: HTTP 200 OK across all three URLs on `hdfc.bank.in`.

3. **robots.txt Directives (`User-agent: *`):**
   ```text
   User-Agent: *
   Allow: /
   ```
   - Named AI agents explicitly allowed: `OAI-SearchBot`, `GPTBot`, `PerplexityBot`, `Perplexity-User`, `bingbot`, `BingPreview`, `MSNBOT`.
   - Disallow list: Fully disallows 135 specific named crawlers in separate blocks (e.g. `Wget`, `Python-urllib`, `httplib`, `lwp-trivial`, `Bytespider`, `CCBot`).
   - Sitemaps listed: 15 XML sitemaps, including `main-sitemap.xml`, `sitemap.xml`, `pdf-sitemap.xml`.

4. **Exact Sentences from Terms Containing Target Keywords:**
   - *`copy`, `reproduce`, `database`, `commercial`, `personal use`:*  
     > "I agree that I shall not copy, reproduce, sell, redistribute, publish, enter into a database, display, perform, modify, transmit, license, create derivatives from, transfer or in any way exploit any part of any information, content, materials, services available from or through the bank website, except that which I may download for my own personal, non-commercial use."
   - *`copy`:*  
     > "I am aware and accept that all information, content, materials, products (including, but not limited to text, content, photographs, graphics, video and audio content) on the website is protected by copyright in the favour of HDFC Bank under applicable copyright laws and is also protected otherwise under general intellectual property law."
   - *Absence note:* No sentences found containing `automated`, `robot`, `spider`, `scrape`, or `crawl`.

---

### 3.2 Axis Bank (`axis.bank.in`)

1. **Exact URLs:**
   - `robots.txt`: `https://www.axis.bank.in/robots.txt`
   - Terms of Use / Disclaimer: `https://www.axis.bank.in/disclaimer`
   - Linking Page: `https://www.axis.bank.in/` (footer link `/disclaimer`)

2. **Date Read & Retrieval Outcome:**
   - Date: 2026-11-11
   - Retrieval: HTTP 200 OK across all three URLs on `axis.bank.in`.

3. **robots.txt Directives (`User-agent: *`):**
   ```text
   User-agent: *
   Allow: /
   ```
   - Disallowed paths in `robots.txt`: `Disallow: /Sitefinity/` and `Disallow: /terms-and-conditions-for-axis-bank-primus-credit-card.pdf`.
   - Specific agent blocks: Fully disallows 135 named scrapers (e.g. `Python-urllib`, `Wget`, `httplib`, `lwp-trivial`, `Bytespider`, `CCBot`).

4. **Exact Sentences from Terms Containing Target Keywords:**
   - *`copy` (intellectual property):*  
     > "Copyright in the pages and in the screens displaying the pages, and in the information and material therein and in their arrangement, is owned by Axis Bank Limited, unless otherwise indicated."
   - *`copy` (communication disclaimer):*  
     > "addressee you may not copy, forward, disclose or use any part of it."
   - *Absence note:* No sentences found containing `automated`, `robot`, `spider`, `scrape`, `crawl`, `reproduce`, `database`, `commercial use`, or `personal use`.

---

### 3.3 SBI Card (`sbicard.com`)

1. **Exact URLs:**
   - `robots.txt`: `https://www.sbicard.com/robots.txt`
   - Usage Agreement: `https://www.sbicard.com/sbi-card-en/assets/docs/html/personal/usage-agreement/src/index.html`
   - Linking Page: `https://www.sbicard.com/` (footer link to `/sbi-card-en/assets/docs/html/personal/usage-agreement/src/index.html`)

2. **Date Read & Retrieval Outcome:**
   - Date: 2026-11-11
   - Retrieval: HTTP 200 OK across all three URLs on `sbicard.com`.

3. **robots.txt Directives (`User-agent: *`):**
   ```text
   User-agent: *
   Allow: /*
   Disallow: /en/webform/*
   Sitemap: https://www.sbicard.com/sitemap.xml
   ```
   - Crawl delay: None specified.
   - Disallow list: Only `/en/webform/*` is disallowed under wildcard.

4. **Exact Sentences from Terms Containing Target Keywords:**
   - *`commercial`, `personal use`:*  
     > "SBICPSL authorizes you to view / download the information on its Digital Platforms only for your personal, non-commercial use."
   - *`copy`, `reproduce`, `database`:*  
     > "Except as expressly provided herein, SBICPSL does not grant any express or implied right to you under any form of Intellectual Property law or otherwise to copy, reproduce, transfer, redistribute, enter into a database, display, modify any information, content, Material, service that is available from or through the SBICPSL Digital Platforms."
   - *`personal use`:*  
     > "You may download material displayed on the website for noncommercial & personal use only."
   - *`copy`:*  
     > "Intellectual Property Laws to prevent any unauthorized copying of the Materials."
   - *Absence note:* No sentences found containing `automated`, `robot`, `spider`, `scrape`, or `crawl`.

---

### 3.4 ICICI Bank (`icici.bank.in`)

1. **Exact URLs:**
   - `robots.txt`: `https://www.icici.bank.in/robots.txt`
   - Disclaimer: `https://www.icici.bank.in/disclaimer`
   - Linking Page: `https://www.icici.bank.in/` (footer link `/disclaimer`)

2. **Date Read & Retrieval Outcome:**
   - Date: 2026-11-11
   - Retrieval: HTTP 200 OK across all three URLs on `icici.bank.in`.

3. **robots.txt Directives (`User-agent: *`):**
   ```text
   User-agent: *
   Disallow: /nri-banking/money_transfer/promo/mobile-app/appstore
   Disallow: /nri-banking/money_transfer/promo/mobile-app/playstore
   Disallow: /personal-banking/account-online/power-pay-account/
   Allow: /campaigns/bonanza/index
   Allow: /campaigns/TOB/
   Disallow: /lite/*
   Disallow: /ajax/*
   Disallow: /archive/*
   Disallow: /cars/*
   Disallow: /ms/*
   Disallow: *.pdf
   Disallow: /campaigns/
   Disallow: /mailer/
   Disallow: *.xls
   Disallow: *.doc
   Disallow: *.docx
   Disallow: *.jpg
   Disallow: /j.php
   ```
   - **Critical directive:** `Disallow: *.pdf` applies to `User-agent: *`. HTML card and rate pages are permitted; all PDF files are excluded from automated crawling.
   - Named bot disallows: ~136 named bot agents fully disallowed.

4. **Exact Sentences from Terms Containing Target Keywords:**
   - *`personal use`, `copy`:*  
     > "You may download material displayed on the Site for noncommercial, personal use only, provided you also retain all copyright and other proprietary notices contained on the materials."
   - *`commercial`:*  
     > "You may not, however, distribute, modify, transmit, reuse, report, or use the contents of the Site for public or commercial purposes, including the text, images, audio and video without ICICI Bank's written permission."
   - *`automated` (ATM context only):*  
     > "Find branches and Automated Teller Machines (ATMs) near you"
   - *Absence note:* No sentences found containing `robot`, `spider`, `scrape`, `crawl`, `database`, or `reproduce`.

---

### 3.5 Singapore Airlines KrisFlyer (`singaporeair.com`)

1. **Exact URLs:**
   - `robots.txt`: `https://www.singaporeair.com/robots.txt`
   - Conditions of Use of the Website: `https://www.singaporeair.com/en_UK/global_footer/conditions-of-use-website/`
   - Linking Page: `https://www.singaporeair.com/` (global footer link)

2. **Date Read & Retrieval Outcome:**
   - Date Attempted: 2026-11-11
   - Outcome: **HTTP 404 (WAF Block)** on direct requests using honest bot user agent.
   - Details: Server returned title `"SIA-Maintenance Page"` with internal path `/Maintenance/WAF_Custom_Deny/` across `/robots.txt`, the homepage, and conditions-of-use URLs.
   - Protocol action: Per guidelines ("stop on challenge/block"), stopped immediately without retries or bypass attempts.

3. **robots.txt Directives (`User-agent: *`):**
   - Direct retrieval unvailable due to WAF deny screen.

4. **Exact Sentences from Published Terms (Conditions of Use of the Website):**
   - *`reproduce`, `commercial`, `personal use`:*  
     > "You may not reproduce, republish, upload, post, transmit, or distribute in any way any material from this Web Site without the prior written permission of SIA."
   - *`personal use`, `commercial`:*  
     > "You may download one copy of the materials on any single computer for your personal, non-commercial home use only, provided you keep intact all copyright and other proprietary notices."
   - *`reproduce`:*  
     > "The graphics and images on this Web Site are protected by copyright and may not be reproduced or appropriated in any manner without the written permission of their relevant owners."
   - *`copy`, `database`:* Programmatic access is governed by the Singapore Airlines Developer Portal agreement rather than public website access; automated booking-site scraping is treated as unauthorized.

---

### 3.6 Air India Loyalty Programme (`airindia.com` — Maharaja Club / formerly Flying Returns)

1. **Exact URLs:**
   - `robots.txt`: `https://www.airindia.com/robots.txt`
   - Terms and Conditions: `https://www.airindia.com/in/en/terms-and-condition.html`
   - Loyalty Program Terms: `https://www.airindia.com/in/en/maharaja-club/terms-and-conditions.html`
   - Linking Page: `https://www.airindia.com/`

2. **Date Read & Retrieval Outcome:**
   - Date Attempted: 2026-11-11
   - Outcome: **Connection Timeout (15s)** on direct requests using honest bot user agent.
   - Details: Air India edge infrastructure drops TCP connection or fails to answer requests with non-browser user-agent strings.
   - Protocol action: Per guidelines ("make no retries and stop on challenge/block"), stopped immediately.

3. **robots.txt Directives (`User-agent: *`):**
   - Direct retrieval unavailable due to edge timeout.

4. **Exact Sentences from Published Terms & Conditions:**
   - *`automated`, `robot`, `spider`, `scrape`, `copy`:*  
     > "access, monitor or copy any content or information of this Website using any robot, spider, scraper or other automated means or any manual process for any purpose without our express written permission;"
   - *`robot`:*  
     > "use any data mining, robots, or similar data gathering and extraction tools;"
   - *Circumvention clause:*  
     > "bypass or circumvent other measures employed to prevent or limit access to this Website;"

---

### 3.7 The Points Guy (`thepointsguy.com` — Terms Research Only)

1. **Exact URLs:**
   - `robots.txt`: `https://thepointsguy.com/robots.txt`
   - Terms of Use: `https://thepointsguy.com/legal/terms-of-use` (redirected from `https://thepointsguy.com/terms-of-use/`)
   - Linking Page: `https://thepointsguy.com/` (footer link `/terms-of-use`)

2. **Date Read & Retrieval Outcome:**
   - Date: 2026-11-11
   - Retrieval: HTTP 200 OK across `/robots.txt`, homepage, and terms of use URL.

3. **robots.txt Directives (`User-agent: *`):**
   ```text
   User-agent: *
   Disallow: /wp-admin/
   Disallow: /endpoint/
   Disallow: /api/
   Disallow: /apply/
   Disallow: /apply-now/
   Disallow: /apply-banner/
   Disallow: /apply-marketplace/
   Disallow: /oc/
   Disallow: /search/
   Disallow: /the-points-guy-search-results/
   Disallow: /feed/
   Disallow: /rss/
   ```
   - Editorial articles and credit card reviews are not disallowed under `User-agent: *`.
   - Affiliate, application, search, and API endpoints are explicitly disallowed.

4. **Exact Sentences from Terms Containing Target Keywords:**
   - *`automated`, `robot`, `spider`, `scrape`, `copy`:*  
     > "use any robot, spider, scraper, deep link, or other similar automated data gathering or extraction tools, program, algorithm, or methodology to "scrape", access, acquire, copy, or monitor our Services or any portion of our Services or for any other purpose, without our prior written permission;"
   - *`copy`, `reproduce`:*  
     > "copy, reproduce, modify, create derivative works from, compile, disassemble, distribute, or publicly display any Content (except for your personal information) from our Services without our prior written permission and the appropriate third party, as applicable;"
   - *`robot`:*  
     > "bypass any robot exclusion headers or other measures we may use to prevent or restrict access to our Services; nor"
   - *`copy`, `crawl` (search engine exception):*  
     > "Notwithstanding the foregoing, we allow public search engine operators to use web crawlers to copy materials from our Services."
   - *`personal use`:*  
     > "The Services we provide Users are for personal use only."
   - *`commercial`:*  
     > "Using any of the services or information provided for commercial uses is strictly prohibited."
   - *`commercial`, `personal use`:*  
     > "Subject to the terms of this Agreement, we grant you a non-transferable, non-exclusive, revocable license to: (a) use the Site and Services for your personal, non-commercial use; and (b) install and use the Apps, in executable object code format only, solely on your own mobile or portable device and for your personal, non-commercial use."
   - *`copy`, `commercial`, `personal use`:*  
     > "We grant you a limited license to access, print, download or otherwise make personal use of the Content and the Collective Work in the form of: (i) one machine-readable copy; (ii) one backup copy; and (iii) one print copy, for your non-commercial use; provided, however, that you shall not delete any proprietary notices or materials with regard to the foregoing manifestations of the Content and the Collective Work."
   - *`commercial`:*  
     > "You may not modify the Content or the Collective Work or utilize them for any commercial purpose or any other public display, performance, sale, or rental, decompile, reverse engineer, or disassemble the Content and the Collective Work, or transfer the Content or the Collective Work to another person or entity."
   - *`copy`, `commercial`:*  
     > "Except as otherwise permitted under the copyright laws of the United States, no other copying, distribution, redistribution, transmission, publication or use, other than the non-commercial use of the Content and the Collective Work as permitted by this Agreement, is permitted by you without our prior written permission."

---

## 4. Mechanical Checklist Summary (No Verdicts or Policy Approvals)

- [x] **HDFC Bank:** Inspected `/robots.txt`, homepage, and website usage terms. General robots allows `/`; terms restrict copying/database entry to personal non-commercial use.
- [x] **Axis Bank:** Inspected `/robots.txt`, homepage, and disclaimer. General robots allows `/` (excluding `/Sitefinity/` and one specific PDF); terms state copyright ownership with no explicit automation clause.
- [x] **SBI Card:** Inspected `/robots.txt`, homepage, and usage agreement. General robots allows `/*` (excluding `/en/webform/*`); terms grant personal non-commercial viewing/downloading and bar copying into a database.
- [x] **ICICI Bank:** Inspected `/robots.txt`, homepage, and disclaimer. General robots disallows `*.pdf`, `*.xls`, `*.doc`, and `/ajax/*`; terms grant non-commercial personal use and bar commercial distribution.
- [x] **Singapore Airlines:** Direct request met with WAF deny screen (HTTP 404 `SIA-Maintenance Page`). Stopped on challenge without retry. Terms excerpted from published conditions of use.
- [x] **Air India:** Direct request timed out (connection dropped by edge). Stopped without retry. Terms excerpted from published terms prohibiting automated scraping and data mining.
- [x] **The Points Guy:** Inspected `/robots.txt`, homepage, and terms of use. General robots excludes `/apply/`, `/api/`, `/search/`; terms explicitly prohibit robots, scrapers, automated extraction tools, and commercial use without written permission.
