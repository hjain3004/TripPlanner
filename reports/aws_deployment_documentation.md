# AWS deployment, cost, operations, and Claude runtime documentation

**Status:** documentation only. Planned, not provisioned.

| | |
|---|---|
| Base | `6a8cb52124d9bf79ef4a8355a1633789f438806d` (`codex/d1-deployment-foundation`) |
| Branch | `codex/d1-aws-deployment-documentation` |
| Pricing and policy research date | 2026-10-22 |
| Region assumption | `us-east-1` |
| Pushed / PR | No |

## Scope

Planning documents for hosting the D1 stack on AWS with ~$125 of AWS promotional credit and $50 of
Anthropic credit, plus the native Claude runtime design. No phase was started.

## Files

| File | Change |
|---|---|
| `docs/AWS_DEPLOYMENT_PLAN.md` | New — canonical architecture, Claude runtime design (§ 22), phases D2–D5 and L1 |
| `docs/AWS_COST_AND_CAPACITY.md` | New — canonical cost, credit, and capacity estimates |
| `docs/AWS_OPERATIONS_RUNBOOK.md` | New — planned procedures, marked not yet executed |
| `docs/INDEX.md`, `docs/CURRENT_STATE.md`, `docs/INFRASTRUCTURE.md` | Links and a "planned, not provisioned" statement; nothing else changed |
| `DEVIATIONS.md` | New section with 10 Tier-C entries |
| `reports/aws_deployment_documentation.md` | This report |

## Sources

First-party only: AWS documentation and pricing pages, Anthropic documentation and pricing pages, and
GitHub documentation and changelog. Each document lists its sources with links. One disclosed method:
EC2 rates were read from the public price file that AWS's own EC2 pricing page loads (publication
2026-10-15T19:13:16Z), because the page renders prices with JavaScript.

## Decisions

1. **Account profile is a human decision.** Free account plans cannot redeem promotional credits; the
   Paid plan charges beyond credits. Profile F (Free) is the conservative default; Profile P (Paid, uses
   the promotional credit) is an option only with recorded human approval. Both share one architecture.
   Nothing here approves the exception to the USD 0 rule.
2. **One EC2 instance running the D1 Compose stack**, because SQLite, process-local jobs and locks, and
   per-process budgets require exactly one backend replica.
3. **2 GiB memory target.** `t4g.small` preferred if measured memory fits; `t3.small` if Arm fails;
   `t4g.medium` is not Free Tier eligible (correction to the brief).
4. **Pay-as-you-go CloudFront without WAF** as the baseline, because the flat-rate plan's account
   constraints probably exclude a credit-holding new account; tried in the console at D5.
5. **Origin TLS through ACME DNS-01** at nginx, origin locked to the CloudFront prefix list plus a secret
   header.
6. **OIDC deploys by digest through SSM Run Command**; approval is a manual dispatch because GitHub Pro
   private repositories lack required reviewers.
7. **Native Anthropic Messages API client** behind the existing `LLMClient` protocol; structured outputs,
   fixed Haiku/Sonnet routing, no OpenAI compatibility layer, persistent content-free usage ledger.
8. **Budgets are notifications**, not caps; Anthropic's prepaid credit with auto-reload off is the
   structural stop for LLM spend.

## Headline figures (estimates)

- AWS: `t4g.small` stack ≈ $20.39/month; six-month schedule ≈ $105.90; allocation hosting $97, images,
  backups, and logs $10, drills $5, reserve $13.
- Claude (planner modelled as its real discovery loop): $0.0546 per plan baseline, $0.4847
  conservative, $0.0430 optimized; ceiling $0.80 at today's 25-call bound, $0.27 at the planned 10-call
  bound. $50 split $5 / $10 / $25 / $10; global ceiling ≈ 3.8 baseline (0.43 conservative) plans per day.
- Beta cap: 50 invited users, a policy limit pending the D5 load test. No capacity was measured.

## Known unknowns

Recorded in [plan § 28](../docs/AWS_DEPLOYMENT_PLAN.md#28-known-unknowns): flat-rate plan eligibility;
credit expiry and application order; activity credit amounts; Free plan service list; memory footprint;
real token counts and cache-read rates; Anthropic rate-limit tier; SDK proxy behaviour; exact gp3 and S3
Standard rates.

## Verification

- Relative links and heading anchors in all changed documents: 0 broken (scripted check).
- Scan of the new documents for 12-digit account IDs, API-key and access-key patterns, and email
  addresses: none found.
- Scan for claims of high availability, horizontal scaling, zero downtime, provisioning, or deployment:
  only explicit non-claims.
- Changed files: the 8 documentation files listed above; no other path.
- `make gate` on the first documentation commit `3a2b499`: GATE PASSED — 1,883 passed, 1 skipped;
  mypy `--strict` clean (177 + 5 source files); ruff clean, legacy ratchet 6 of 12; `GOLDENS_OK`,
  `CONTRACT_OK`, `BRIEFS_IDENTICAL`, `TREE_CLEAN`. The gate is run again on the final commit after the
  review fixes; that result is reported in the hand-off.

## Independent review

One whole-branch review (separate agent, read-only, spot-checked against first-party pages). Critical: none.
Important, all fixed:

1. The planner is a bounded tool loop (up to 6 calls per draft), not one call — the cost model and the
   native-client design (§ 22.3) were rewritten around it, and L1 lowers the per-request ceiling to 10.
2. The characters-per-token ratio was mis-attributed to Anthropic — relabelled as an assumption.
3. Containers could reach instance metadata — IMDSv2 hop limit 1 added to the plan and runbook.
4. The plan contradicted itself on secrets in Terraform state — the origin-header exception is stated.
5. Profile P was presented as recommended — Profile F is now the conservative default.

Minor, fixed: checkpoint shift (12 days, not 9); Sonnet share (> 99%); hosting allocation ($97);
staging hours stated; ECR figure relabelled as an estimate; critic `max_tokens` overflow noted; Compose
project name `tripwise-d1`; build job declares `environment: production`; SSM output must not print
secrets; this section replaces a dangling reference. Not changed: WAF and NAT prices appear in both the
plan and the cost model, kept so each exclusion is self-explanatory.

## Confirmations

- No AWS account, resource, credential, or credit was created or used. No Anthropic key was created and
  no Anthropic API request was made. No billing experiment was run. No public deployment occurred.
- Network access during this task was limited to reading public documentation and pricing pages.
- No application code, spec, OpenAPI contract, frontend, test, seed, golden value, or Tier-F behaviour
  changed. `AGENTS.md` and `CLAUDE.md` were not touched.
- The primary checkout and all other worktrees and branches were not modified. Nothing was pushed.
