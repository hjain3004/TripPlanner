# Instagram reel-to-trip — access and feasibility preflight

**Type:** research only. Nothing was built, configured, requested, or executed.
**Date:** 2026-10-26. **Base:** `6428b78` (FI1 merge, PR #18), branch `codex/instagram-reel-access-preflight`.
**Profile:** `student_noncommercial`, USD 0 out-of-pocket.

**Labels used throughout**

| Label | Meaning |
|---|---|
| **[VERIFIED]** | Stated in a primary source listed in § 12, read on 2026-10-26 |
| **[RECOMMENDATION]** | Our architectural proposal; not a Meta or Expedia statement |
| **[ASSUMPTION]** | Believed but not documented; must not be relied on |
| **[UNRESOLVED]** | Needs an authorized live test (§ 9) |
| **[HUMAN REVIEW]** | Legal, compliance, or policy interpretation a person must decide |

---

## 1. Conclusions

| Capability | Verdict | Why |
|---|---|---|
| Receive and reply to DMs on our own professional account | **Conditional go** | The documented route exists and needs no App Review for an account we own [VERIFIED]. Conditions: the app must be **Live** to receive notifications for app users [VERIFIED]; it is **[UNRESOLVED]** whether DMs from members of the public (who hold no role on our app) are delivered and answerable under Standard Access; a public HTTPS endpoint, a Meta credential, and this feature itself each need human approval in this repository (§ 10). |
| Interpret accessible reel content | **Conditional go for metadata only; no-go for video analysis** | Meta documents that a shared reel arrives with a title, a URL, and a video ID [VERIFIED]. What the URL serves, how long it lives, and whether downloading and analysing a third party's video is permitted are **[UNRESOLVED]** and **[HUMAN REVIEW]**. A caption-and-confirmation flow is feasible without touching the video. |
| Hand confirmed trip preferences to the existing planning backend | **Go (technical)** | The conversational session, brief confirmation, planning, saved trips, and post-plan actions already exist (§ 8). New work is a channel adapter, account linking, and a destination pre-fill; all of it is unspecified scope that needs a human-approved `SCOPE+` decision first (§ 10). |

**No promise is made** of arbitrary-reel coverage, access approval, permanent zero cost, or Expedia-equivalent access.

---

## 2. Q1 — Which route fits our own single professional account

- **[VERIFIED]** Meta offers two configurations: "Instagram API with Instagram Login serves Instagram professional accounts without requiring a linked Facebook Page", and "Instagram API with Facebook Login serves Instagram professional accounts linked to a Facebook Page" ([overview](https://developers.facebook.com/docs/instagram-platform/overview)).
- **[VERIFIED]** Messaging permissions differ: Instagram Login uses `instagram_business_manage_messages`; Facebook Login uses `instagram_manage_messages` through the Messenger Platform's Instagram Messaging API (same page).
- **[VERIFIED]** "If your app only serves your Instagram professional account or an account you manage, Standard Access is all your app needs." (same page)
- **[RECOMMENDATION]** Use **Instagram API with Instagram Login**, scopes `instagram_business_basic` and `instagram_business_manage_messages`, Standard Access, and one professional account we own. It avoids creating and linking a Facebook Page.

## 3. Q2 — Configuration, permissions, tokens, access, review, modes, windows

### 3.1 Our account versus other businesses' accounts

| Topic | Our own account (this use case) | Other businesses' accounts (not this use case) |
|---|---|---|
| Access level | Standard Access [VERIFIED] | Advanced Access [VERIFIED] |
| App Review | "Not required" for "My app is only for a business I own or manage" [VERIFIED, [app review](https://developers.facebook.com/docs/instagram-platform/app-review)] | Required [VERIFIED] |
| Business Verification | Not stated as required for Standard Access | Required with Advanced Access [VERIFIED, overview] |
| Caveat | "Some features may not work properly until your app has been granted Advanced Access" [VERIFIED, [messaging API](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api)] — which features is not stated **[UNRESOLVED]** | — |

### 3.2 Development versus Live

- **[VERIFIED]** "Apps in Development mode can only request permissions from role users", and data generated in Development mode "can only be seen by role users" ([app modes](https://developers.facebook.com/docs/development/build-and-test/app-modes)).
- **[VERIFIED]** "Your app must be published or **Live** to receive notifications for app users." ([webhook setup](https://developers.facebook.com/documentation/instagram-platform/webhooks/setup))
- **[VERIFIED]** In Live mode, apps "can request permissions from anyone, but only permissions approved through App Review"; for consumer apps, Standard Access features "are active only for role users" (app modes page).
- **[VERIFIED]** Testers "must have a role on your app, grant your app access to all the required permissions, and have a role on the Instagram professional account that owns the app" (messaging API page).
- **[UNRESOLVED]** The decisive question: with the app Live, Standard Access, and only our own account connected, does a **message from a member of the public** generate a `messages` webhook and accept a reply? The public sender never grants our app a permission, and Meta's pages neither confirm nor rule this out. Developer anecdotes are not used as evidence.
- **[UNRESOLVED]** What Meta requires before this app type can go Live (privacy policy, data-deletion URL, category). The app-modes page says to go Live "after you have completed app development and have completed App Review" without listing prerequisites, while the App Review page says review is not required for own-business Standard Access. The documentation read does not reconcile the two.

### 3.3 Tokens

- **[VERIFIED]** ([business login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login)) The authorization code is valid for one hour and usable once; the long-lived Instagram User access token is valid for 60 days; it can be refreshed with `GET /refresh_access_token?grant_type=ig_refresh_token` when it is at least 24 hours old, unexpired, and `instagram_business_basic` was granted; "Tokens that have not been refreshed in 60 days will expire and can no longer be refreshed." The `redirect_uri` must exactly match a configured URI.
- **[VERIFIED]** The old `business_*` scope values were deprecated on 2025-01-27 (same page).
- **[RECOMMENDATION]** One token, for our own account only, stored as a secret, refreshed on a schedule well inside 60 days, with an alarm on refresh failure. No traveler ever grants TripWise an Instagram token.

### 3.4 Messaging windows and limits

- **[VERIFIED]** "For most user actions, it lasts 24 hours"; after a Click-to-Direct ad "the window may last up to 7 days"; a reply may use the human-agent tag for "the separate 7-day Human Agent window" (messaging API page). Developer Policy 5.6.1.a states the same 24-hour rule ([developer policies](https://developers.facebook.com/devpolicy/), last updated 2026-02-03).
- **[VERIFIED]** Limitations include: group messaging unsupported; one customer per conversation; inactive Requests-folder messages older than 30 days not returned; webhook delivery does not mark messages as read (messaging API page).
- **[VERIFIED]** Rate limits ([overview](https://developers.facebook.com/docs/instagram-platform/overview)): Send API 100 calls/s per professional account for text, links, reactions, and stickers, and 10 calls/s for audio or video; Conversations API 2 calls/s per account.
- **[VERIFIED]** Policy 5.2.b requires respecting opt-out requests immediately.
- **[RECOMMENDATION]** Design the automated flow to finish inside 24 hours. The human-agent tag is used only by a human, never by automation.

## 4. Q3 — What arrives when a traveler shares content by DM

### 4.1 Documented attachment types

| What the traveler sends | Attachment type | Payload Meta documents | Source |
|---|---|---|---|
| An Instagram reel | `ig_reel` | title, url, video id | [VERIFIED] [changelog 2024-06-11](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/changelog) |
| A Facebook reel | `reel` | title, url, video id | [VERIFIED] same entry |
| Reel video-id field name | `reel_video_id`: "ID of the video associated with the attached reel. Applicable to attachment type: `reel` and `ig_reel`" | — | [VERIFIED] [Messenger messages reference](https://developers.facebook.com/docs/messenger-platform/reference/webhook-events/messages/) |
| An Instagram post | `ig_post` (replacing legacy `share`) | media ID, URL, title (caption) | [VERIFIED] changelog 2025-10-30 and 2026-04-27 |
| Legacy post share | `share`, "deprecated after Feb 2026"; removal rolling out gradually | url | [VERIFIED] [webhook examples](https://developers.facebook.com/docs/instagram-platform/webhooks/examples), changelog 2026-04-27 |
| A video the traveler uploads | `video` | url | [VERIFIED] webhook examples |

- **[VERIFIED]** "Only the URL for the shared media or post is included in the webhooks notification when a customer sends a message with a share." (messaging API page). This conflicts with the richer `ig_post` and `ig_reel` payloads in the changelog; the documents are **inconsistent**, and only a live payload resolves it.
- **[VERIFIED]** `title` is defined as "Title of the attachment. Applicable to … `reel`, `ig_reel`, `post` and `ig_post`" (Messenger reference). For posts the changelog calls it the caption; for reels it does not say whether the title equals the caption.

### 4.2 Not documented — must be established by a live test

- **[UNRESOLVED]** Whether the reel `url` is a playable media file, a CDN link, or a page link, and how long it remains valid. No expiry statement was found.
- **[UNRESOLVED]** Whether a **thumbnail** is delivered. No thumbnail field is documented for `ig_reel`.
- **[UNRESOLVED]** Whether `title` contains the full caption, hashtags, or location-tag text.
- **[UNRESOLVED]** What arrives for a reel from a **private** account, or a reel that is later deleted.
- **[UNRESOLVED]** Whether any documented endpoint lets our app fetch further metadata for a third party's `reel_video_id`. None was found; assume none.
- **[ASSUMPTION]** A reel's location sticker or tag is not delivered; no field for it is documented.

### 4.3 Recommendation

**[RECOMMENDATION]** Build the first version on **text only**: the attachment `title`, the traveler's own message text, and explicit confirmation questions back to the traveler ("Is this Lisbon, Portugal?"). Do not download, transcribe, or frame-sample the video. This works whether or not the URL is fetchable, keeps the LLM role small and money-free, and avoids the rights question in § 5.

## 5. Q4 — Permissions for processing, retention, attribution, deletion, and model use

### 5.1 What the terms say

- **[VERIFIED]** Platform Terms ([terms](https://developers.facebook.com/terms/dfc_platform_terms/), last updated 2026-02-03):
  - § 3.a.viii prohibits "Processing Platform Data for purposes other than the applicable permitted purposes set forth in Meta's Developer Docs."
  - § 3.a.v prohibits "Processing Platform Data without valid User consent in order to build or augment user profiles for any purpose."
  - § 3.a.iv prohibits "Selling, licensing, or purchasing Platform Data."
  - § 3.c.ii.2 permits sharing "with your Service Provider in order for them to provide the services you requested."
  - § 3.d.i requires updating or deleting Platform Data promptly on request from Meta or the user, and deleting it when no longer necessary or when "a User requests their Platform Data be deleted or no longer has an account with you."
  - § 6.a requires security safeguards and forbids transferring "Meta user IDs, access tokens, or app secrets."
- **[VERIFIED]** Developer Policies (last updated 2026-02-03):
  - § 5.6.4: "Don't use any data obtained from us about the people you reach in Messenger and/or Instagram Messaging, other than the content of message threads or calls, for any purpose other than as reasonably necessary to support the message or calling types you elect to use."
  - § 6.1: "Comply with any requirements or restrictions imposed on usage of Instagram user photos and videos … You are solely responsible for making use of User Content in compliance with owners' requirements or restrictions."
  - § 6.2: "Don't use the Instagram Platform to simply display User Content, import or backup content, or manage Instagram relationships, without our prior permission."
  - § 10.7.e: "Don't use Meta's data to build or augment any user profiles."
- **[VERIFIED]** "Apps that access user data must provide a way for users to request that their data be deleted", through a data-deletion instructions URL or a signed HTTPS callback returning `{url, confirmation_code}` ([data-deletion callback](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback/)).
- **[VERIFIED]** Neither the Platform Terms nor the Developer Policies read contain a provision expressly about training or applying AI or ML models.

### 5.2 Questions for human review

A shared link does not establish permission to download or analyse the creator's video. These are **[HUMAN REVIEW]** items, not conclusions:

1. Whether downloading, transcribing, or frame-analysing a **third-party creator's** reel is permitted under § 6.1, the creator's rights, and Instagram's Terms of Use (not reviewed in this preflight).
2. Whether sending the reel title and the traveler's messages to an LLM provider is a "Service Provider" use under § 3.c.ii.2 and a permitted purpose under § 3.a.viii and § 5.6.4.
3. Whether storing a link between an Instagram-scoped ID and a TripWise account, with the traveler's consent, is "building or augmenting a user profile" (§ 3.a.v, § 10.7.e) or a permitted support use.
4. What attribution to the creator, if any, a reply that names the reel must carry.
5. The privacy-policy and deletion-instructions wording; `CLAUDE.md` reserves legal and compliance wording for a human.

### 5.3 Proportionate data rules

**[RECOMMENDATION]**
- Store no video, thumbnail, or caption beyond the active planning conversation; keep the attachment `title` only inside the planning session, which already expires.
- Keep the Instagram-scoped ID ↔ TripWise account link only while linked; delete it on unlink, on account deletion (spec 17 § 6), and on a Meta deletion request.
- Never put the Instagram handle, scoped ID, email, display name, or `last4` in an LLM prompt (spec 17 § 7).
- Log webhook metadata only (event id, type, timing), never message bodies.

## 6. Q5 — What Expedia and Meta have publicly said

### 6.1 Verified public evidence

- **[VERIFIED]** Expedia's Trip Matching page ([expedia.com/tripmatching](https://www.expedia.com/tripmatching), read 2026-10-26):
  - It is "an AI-powered feature from Expedia that turns public reels on Instagram into bookable travel itineraries", used by sharing a reel to Expedia "as a direct messaging on Instagram."
  - Expedia "uses a mix of AI models as well as proprietary information."
  - A reply may not arrive if "The reel you shared was not public, or not travel related", if "It was a video or post instead of a reel", or under heavy demand.
  - It is "built and optimized for the U.S. market" and is not available outside Instagram.
- **[VERIFIED]** Expedia newsroom, 2026-05-19, "Expedia Group Unveils New AI Experiences … at Explore 2026" ([newsroom](https://www.expedia.com/newsroom/expedia-group-unveils-new-ai-experiences-expands-travel-ecosystem-and-launches-philanthropy-program-at-explore-2026/)): "Expedia and Meta are taking the next step in their collaboration: testing AI conversations on ads … This follows last year's launch of Trip Matching—an innovative feature that lets travelers create itineraries inspired by Instagram Reels."
- **Inaccessible:** the original Trip Matching launch release (`expedia.com/newsroom/expedia-trip-matching/`) returned HTTP 429 to the fetch tool and then a 404 page in a browser on 2026-10-26. Search results describe it as a May 2025 release; that is not treated as verified.
- No Meta-side announcement of a Trip Matching partnership was found on Meta's newsroom or developer domains.

### 6.2 Not supported by any evidence found

- That Expedia uses privileged, non-public, or Advanced-only API access for Trip Matching.
- That Meta granted Expedia exclusivity, special pricing, or content rights.
- That any right or capability Expedia has is available to TripWise.

Expedia states a "collaboration" with Meta on **ads**, and that Trip Matching works on **public** reels. Everything beyond that is unknown.

## 7. Q6 — What our integration would require

| Concern | Documented requirement | Recommendation |
|---|---|---|
| HTTPS endpoint | Valid TLS; "Self-signed certificates are not supported" [VERIFIED, webhook setup] | A public HTTPS route on the eventual deployment. Public deployment needs explicit approval (spec 06 § 7(e)), and infra work is paused. |
| Verification handshake | GET with `hub.mode=subscribe`, `hub.challenge`, `hub.verify_token`; echo the challenge [VERIFIED] | Constant-time comparison of the verify token. |
| Signature | `X-Hub-Signature-256: sha256=…`, an HMAC-SHA256 of the payload with the app secret [VERIFIED] | Verify on the raw body before parsing; reject on mismatch. |
| Delivery | Respond `200 OK` promptly; retries continue "over the next 36 hours"; "Your server should handle deduplication"; batches up to 1,000 but not guaranteed; undelivered events dropped after 36 hours [VERIFIED] | Acknowledge immediately; durable dedup keyed on the message `mid` (the same pattern as the A3/A4 idempotency ledgers); process asynchronously. |
| Subscription | `POST /subscribed_apps` on the professional account with the selected fields; every selected field goes to every account [VERIFIED] | Subscribe `messages` only. |
| Account linking | Nothing documented for this flow | Reply with a link to TripWise sign-in carrying a single-use, short-lived, signed nonce bound to the sender's scoped ID; the traveler signs in with existing email/password auth (A2) and confirms consent; unlinking lives in the account. Travelers never log in with Instagram, which stays clear of spec 17 § 7's social-login restriction. |
| Privacy and deletion | Deletion URL or signed callback [VERIFIED] | Implement the signed callback; cascade into the link table and any session it created. |
| Abuse | Opt-out respected immediately (5.2.b) [VERIFIED] | Per-sender message and plan quotas; ignore non-reel spam; a global daily LLM ceiling; a kill switch; a human escalation path. |
| Spending | No pricing statement found on the Instagram Platform pages read; this is not evidence that use is free | LLM interpretation must stay inside the USD 0 rule (zero-spend model or prepaid credit). Hosting cost belongs to the paused infra plan. |

## 8. What the existing backend already supplies

| Need | Already on `main` | New work |
|---|---|---|
| Accounts, sessions, CSRF, privacy export and delete | A1/A2 | A link table and its deletion cascade |
| Wallet for personalised optimisation | A3 (`/account/wallet`) | — |
| Conversational interview, brief review, confirmation | CP1/CP2 (`/planning/sessions/*`) | Start a session pre-filled with a confirmed destination |
| Bounded LLM interpretation with a zero-spend guard | CP3 (`/sessions/{id}/interpret`) | A reel-title interpreter role with its own budget |
| Planning, optimisation, provenance | Kernel MVP plus confirmed planning | — |
| Saved trips and re-runs | A4 (`api/saved_trips.py`) | — |
| Post-plan changes | CP4 (`api/post_plan.py`) | — |
| Instagram channel | — | Webhook receiver, signature check, dedup, async worker, send-API client, token refresh, 24-hour window handling |
| Spec coverage | — | A `SCOPE+` decision and a spec for the channel, webhooks (spec 16 § 14 excludes provider webhooks), and the new LLM role (non-negotiable 5 bounds LLM call sites) |

## 9. Q7 — Smallest authorized feasibility experiment (NOT executed)

**Purpose:** answer the § 3.2 and § 4.2 unknowns with one account and a handful of messages.

**Prerequisites (each needs the human):**
1. Approval to create a Meta developer account and app and to hold its credentials (spec 06 § 7(b)).
2. One Instagram professional account owned by the human, plus two personal test accounts: one added as an app tester, one with **no** role.
3. A temporary HTTPS receiver that logs only redacted payload **shapes** (keys, types, attachment `type`, URL host and parameter names; no message text, full URLs, or IDs). Exposing it publicly needs approval (spec 06 § 7(e)).
4. A privacy policy and deletion-instructions page if Live mode demands them; the wording is a human task (§ 5.2).

**Steps and evidence:**

| # | Action | Evidence to capture |
|---|---|---|
| 1 | Configure Instagram Login, Standard Access, scopes `instagram_business_basic` and `instagram_business_manage_messages`; subscribe `messages` | Dashboard screenshots with secrets redacted; whether App Review or Business Verification is demanded |
| 2 | In Development mode, the tester sends text, an `ig_reel` from a public creator, an `ig_post`, and an uploaded video | Redacted payload shapes; presence of `title`, `url`, `reel_video_id`, a media ID, a thumbnail |
| 3 | Same as step 2 with a reel from a **private** account | What arrives, or nothing |
| 4 | Reply to the tester inside 24 hours | Send API response status |
| 5 | Switch to Live (only if no review is demanded); the **no-role** account sends a reel | Whether a webhook arrives; whether a reply succeeds |
| 6 | Inspect a reel `url` **without downloading content**: record scheme, host, and expiry-related parameter names only | Whether it looks like a media CDN link; any expiry hint. Any HEAD or GET request waits for the § 5.2 legal decision. |
| 7 | Refresh the token after 24 hours | Refresh succeeded; new expiry |

**Success:** steps 2, 4, and 5 succeed under Standard Access with no review, and `ig_reel` carries a usable `title`.
**Failure:** step 5 delivers nothing for a non-role sender, or Meta demands App Review or Business Verification for this use.
**Stop immediately if:** a payment method or paid tier is requested; terms beyond the standard developer terms must be accepted; business-verification documents are requested; any payload contains personal data beyond the test accounts; any rate-limit or policy warning appears; or any step would require storing third-party video.

## 10. Blockers in this repository

1. **Out of spec.** No spec covers an Instagram channel. CLAUDE.md requires a `SCOPE+` entry for any unspecified feature, "and the default answer is no." A human must approve the feature before design or code.
2. **Credentials and public endpoint.** A Meta app secret and token (spec 06 § 7(b)) and a public HTTPS webhook (§ 7(e)) both need explicit approval; infra work is paused.
3. **Webhooks.** Spec 16 § 14 places provider webhooks outside the gateway contract; an inbound channel needs its own spec.
4. **LLM call sites.** Non-negotiable 5 fixes the Kernel's call sites; a reel interpreter is a new target-platform role, like CP3's assistant, and needs an explicit specification and a zero-spend guard.
5. **Legal review.** The § 5.2 items must be decided before any video access or LLM processing of shared content.
6. **[UNRESOLVED]** Public-sender delivery under Standard Access (§ 3.2) is the technical make-or-break question.

## 11. Research limitations

- Quotations were extracted through an automated page reader (the fetch tool, plus the built-in browser for Expedia pages). They match the source wording as returned, but a person should spot-check the key ones (§ 3.2 and § 4.1) on the live pages before acting.
- Meta's pages show no per-page "last updated" date except the Platform Terms and Developer Policies (2026-02-03). Meta is moving pages from `/docs/` to `/documentation/` paths, and some sections existed only on the new paths.
- The documents are inconsistent on share payloads (messaging API page: "Only the URL"; changelog: title, URL, and IDs) and on naming ("video id" versus `reel_video_id`).
- The fields matrix mentions "Unified Login", which the pages read do not explain.
- Not reviewed: Instagram Terms of Use, Instagram Community Guidelines, Meta Privacy Policy, Meta's AI-specific terms, and Expedia's AI Terms. These belong to the § 5.2 legal review.
- Expedia's 2025 launch release was inaccessible (429, then 404), and its contents are not used as evidence.
- Link check on 2026-10-26: all 14 Meta URLs returned HTTP 200. Expedia's host returned 429 to scripted requests for all three `expedia.com` URLs (two of them were read successfully in a browser), and the Expedia Group investor URL returned 403.
- No developer anecdotes, mirrors, or search snippets are presented as verified policy.

## 12. Sources (accessed 2026-10-26)

| Source | URL | Status |
|---|---|---|
| Instagram Platform overview | https://developers.facebook.com/docs/instagram-platform/overview | Read |
| Messaging API (Instagram Login) | https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api | Read |
| Business Login (tokens) | https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login | Read |
| App Review | https://developers.facebook.com/docs/instagram-platform/app-review | Read |
| Webhooks overview | https://developers.facebook.com/docs/instagram-platform/webhooks | Read |
| Webhook setup | https://developers.facebook.com/documentation/instagram-platform/webhooks/setup | Read |
| Webhook fields | https://developers.facebook.com/documentation/instagram-platform/webhooks/fields | Read |
| Webhook examples | https://developers.facebook.com/docs/instagram-platform/webhooks/examples | Read |
| Instagram Messaging changelog | https://developers.facebook.com/documentation/business-messaging/instagram-messaging/changelog | Read |
| Messenger `messages` webhook reference | https://developers.facebook.com/docs/messenger-platform/reference/webhook-events/messages/ | Read |
| App modes | https://developers.facebook.com/docs/development/build-and-test/app-modes | Read |
| Data-deletion callback | https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback/ | Read |
| Meta Platform Terms | https://developers.facebook.com/terms/dfc_platform_terms/ | Read (updated 2026-02-03) |
| Meta Developer Policies | https://developers.facebook.com/devpolicy/ | Read (updated 2026-02-03) |
| Expedia Trip Matching | https://www.expedia.com/tripmatching | Read (browser) |
| Expedia Explore 2026 release | https://www.expedia.com/newsroom/expedia-group-unveils-new-ai-experiences-expands-travel-ecosystem-and-launches-philanthropy-program-at-explore-2026/ | Read (browser) |
| Expedia Trip Matching launch release | https://www.expedia.com/newsroom/expedia-trip-matching/ | **Inaccessible** (429, then 404) |
| Expedia Group investor release (May 2025) | https://ir.expediagroup.com/news-and-events/financial-releases/news/news-details/2025/EXPEDIA-GROUP-EXPANDS-B2B-PLATFORM-AND-LAUNCHES-GENAI-PARTNERSHIPS-TO-ENHANCE-TRAVEL-DISCOVERY/ | **Inaccessible** (client-rendered; no content returned) |

## 13. Confirmations

- No Meta or other account, app, credential, token, OAuth flow, webhook, provider call, model call, crawl, or spending occurred.
- Network access was limited to reading the public documentation pages above.
- The change is this report only. No application code, dependency, spec, `AGENTS.md`/`CLAUDE.md`, roadmap, seed, golden value, or other worktree was modified. FI2 and OpenBnB work were not touched.
