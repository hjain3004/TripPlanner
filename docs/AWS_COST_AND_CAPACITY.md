# AWS and Claude cost and capacity (planned — estimates, not measurements)

**Status:** PLANNED. Every figure here is an estimate computed from public pricing and from the
repository's recorded fixtures. **No figure has been measured on AWS or against the Anthropic API,
and nothing here is a capacity promise.** L1 and D5 replace the estimates with measurements.

| | |
|---|---|
| Pricing research date | 2026-10-22 |
| Region assumption | US East (N. Virginia), `us-east-1`; Anthropic default global routing |
| Month | 730 hours |
| Labels | **Exact** = the rate is quoted for this region or globally · **Estimated** = AWS shows only an example rate, or the figure depends on an assumption stated beside it · **Free-Tier-dependent** = $0 only within an allowance · **Usage-dependent** = scales with traffic |

> **Verify before provisioning.** Prices change. Recompute every AWS line in the
> [AWS Pricing Calculator](https://calculator.aws/) and check the Anthropic
> [pricing page](https://platform.claude.com/docs/en/about-claude/pricing) on the day you provision.

This is the canonical cost and capacity document. The architecture and the account profiles P
(Paid plan, promotional credit, residual overage risk) and F (Free plan, no overage) are defined in
[AWS_DEPLOYMENT_PLAN.md § 4](AWS_DEPLOYMENT_PLAN.md#4-spend-controls-and-account-profiles).

---

## 1. Budgets

| Budget | Amount | Rules |
|---|---|---|
| AWS promotional credit | ~$125 | Redeemable only on the Paid account plan (Profile P) |
| AWS sign-up credit | $100 | Both plans; AWS's FAQ gives both 12 and 6 months for its expiry — plan on 6 |
| AWS activity credits | up to $100 | Five activities; per-activity amounts not stated in the documentation reviewed |
| Anthropic API credit | $50 | Prepaid; API calls stop at zero balance when auto-reload is off |
| Out-of-pocket | $0 | `DEVIATIONS.md` 2026-08-02; Profile P needs a recorded human exception |

**Planning rule:** Profile P plans against the **$125 promotional credit alone** and treats the
sign-up and activity credits as an unallocated buffer, because their expiry and the order in which AWS
applies balances are unverified. Profile F has only the $100 sign-up credit plus whatever activities
earn.

## 2. AWS monthly scenarios

### 2.1 Line items (instances running 730 hours)

| Line | Quantity | Rate | Monthly | Label | Source |
|---|---|---|---|---|---|
| `t4g.small` (Linux) | 730 h | $0.0168/h | $12.264 | Exact | [EC2 On-Demand](https://aws.amazon.com/ec2/pricing/on-demand/) ¹ |
| `t3.small` (Linux) | 730 h | $0.0208/h | $15.184 | Exact | same ¹ |
| `t4g.medium` (Linux) | 730 h | $0.0336/h | $24.528 | Exact | same ¹ |
| `c7i-flex.large` (Linux) | 730 h | $0.08479/h | $61.897 | Exact | same ¹ |
| `m7i-flex.large` (Linux) | 730 h | $0.09576/h | $69.905 | Exact | same ¹ |
| Public IPv4 (Elastic IP) | 730 h | $0.005/h | $3.650 | Exact; charged while allocated, even with the instance stopped | [VPC pricing](https://aws.amazon.com/vpc/pricing/) |
| EBS gp3 root | 20 GB | $0.08/GB-month | $1.600 | Estimated (example rate) | [EBS pricing](https://aws.amazon.com/ebs/pricing/) |
| EBS gp3 data | 10 GB | $0.08/GB-month | $0.800 | Estimated (example rate) | same |
| EBS snapshots | ~5 GB-month (7 daily, incremental) | $0.05/GB-month | $0.250 | Estimated; usage-dependent | same |
| ECR storage | ≤ 3.3 GB (5 image pairs; compressed layers are smaller than the 1.09 GB uncompressed pair) | $0.10/GB-month | ≤ $0.330 | Estimated upper bound | [ECR pricing](https://aws.amazon.com/ecr/pricing/) |
| CloudWatch | logs, 1 dashboard, ≤ 10 alarms, agent metrics | — | $1.000 allowance | Free-Tier-dependent; likely $0 within 5 GB logs, 10 metrics, 10 alarms, 3 dashboards | [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/) |
| Route 53 hosted zone | 1 | $0.50/zone-month | $0.500 | Exact; ALIAS queries to CloudFront free | [Route 53 pricing](https://aws.amazon.com/route53/pricing/) |
| CloudFront (pay-as-you-go) | ≤ 1 TB out, ≤ 10 M requests | always-free tier | $0.000 | Free-Tier-dependent; usage-dependent above it | [pay-as-you-go](https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/) |
| ACM public certificate (CloudFront) | 1 | — | $0.000 | Exact | [ACM pricing](https://aws.amazon.com/certificate-manager/pricing/) |
| SSM Session Manager, Run Command, Parameter Store Standard | — | — | $0.000 | Exact | [Systems Manager pricing](https://aws.amazon.com/systems-manager/pricing/) |
| KMS (AWS managed keys) | — | — | $0.000 | Free-Tier-dependent (20,000 requests/month) | [KMS pricing](https://aws.amazon.com/kms/pricing/) |
| AWS Budgets | ≤ 2 action-enabled | — | $0.000 | Exact | [Budgets pricing](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/) |
| S3 backups | < 1 GB | — | ≈ $0.000 | Estimated; the rate was not readable from the pricing page | [S3 pricing](https://aws.amazon.com/s3/pricing/) |

¹ The EC2 pricing page renders prices with JavaScript. These rates were read on 2026-10-22 from the
public price file that page loads (publication date 2026-10-15T19:13:16Z). Confirm them in the
calculator.

**Not in the baseline:** AWS WAF pay-as-you-go ($5.00 per web ACL-month + $1.00 per rule-month +
$0.60 per million requests, [WAF pricing](https://aws.amazon.com/waf/pricing/)) — about $8–9 per
month for three rules; a NAT gateway (AWS's example: $0.045 per hour plus $0.045 per GB in US East
(Ohio), about $33 per month before data, [VPC pricing](https://aws.amazon.com/vpc/pricing/)); an ACM
exportable origin certificate ($7 per FQDN per issuance or renewal) — the fallback to the free ACME
certificate.

### 2.2 Monthly totals

Non-compute subtotal = IPv4 3.650 + EBS 2.400 + snapshots 0.250 + ECR 0.330 + CloudWatch 1.000 +
Route 53 0.500 = **$8.130** (Estimated).

| Scenario | Monthly | Months on $125 | Months on $100 | Free Tier eligible | Use |
|---|---|---|---|---|---|
| `t4g.small` | **$20.39** | 6.1 | 4.9 | Yes | **Small scenario — primary** |
| `t3.small` | $23.31 | 5.4 | 4.3 | Yes | Arm fallback |
| `t4g.medium` | $32.66 | 3.8 | — | **No** (Profile P only) | **Medium scenario**, if 2 GiB fails on Profile P |
| `c7i-flex.large` | $70.03 | 1.8 | 1.4 | Yes | Profile F's only ≥ 4 GiB-class option; not viable |
| `m7i-flex.large` | $78.03 | 1.6 | 1.3 | Yes | Not viable |
| Instance stopped, everything else kept | $8.13 | — | — | — | Idle staging |

**Conservative monthly total for planning: $21** (`t4g.small`, rounded up). With WAF added it would be
about $30.

## 3. Credit lifetime and checkpoints

### 3.1 Example six-month schedule (`t4g.small`)

| Months | Mode | Hosting ¹ | Images, backups, logs ² | Month total |
|---|---|---|---|---|
| 1–2 (D2–D4) | Private staging, instance running ~8 h/day | $10.58 | $1.58 | $12.16 |
| 3–6 (L1–D5) | Running 24 h/day | $18.81 | $1.58 | $20.39 |

¹ EC2 + IPv4 + EBS volumes + Route 53. ² ECR + snapshots + CloudWatch allowance.

Six-month total ≈ 2 × $12.16 + 4 × $20.39 = **$105.90** (Estimated).

### 3.2 AWS credit allocation ($125 promotional credit)

| Allocation | Amount | Covers |
|---|---|---|
| Hosting | $96 | Compute, IPv4, EBS, Route 53 over the schedule above |
| Images, backups, logs | $10 | ECR, snapshots, S3, CloudWatch |
| Drills | $5 | Temporary restore volumes, a second instance for a few hours, snapshot restores |
| Emergency reserve | $14 | A memory-driven move to a larger instance for part of a month, WAF during an incident, or estimate error |
| **Total** | **$125** | |

On **Profile F**, the same schedule needs about $111 including drills, so it depends on earning at least
~$11 in activity credits, or on starting the full-time period later.

### 3.3 Checkpoints

Cumulative planned spend from § 3.1. Compare it with the Billing console's credit balance at each one.

| Day | Planned cumulative | Decision |
|---|---|---|
| 120 | ≈ $65 | Confirm the remaining balance and every credit's expiry date. If spend is more than 15% over plan, cut cost (stop staging off-hours, drop WAF, shrink logs). Rehearse the export. |
| 150 | ≈ $86 | Fix the teardown date. Tell invited users the end date. Take and verify a full export (runbook). |
| 165 | ≈ $96 | Final export verified off AWS. Freeze deploys. Profile P: decide with the human whether the unallocated buffer extends the period — only after confirming its balance and expiry in the console. |
| ≤ 182 | ≈ $106 | **Teardown** (runbook). Profile F: the account closes six months after opening regardless. Profile P: nothing may run into net-of-credit charges. |

Days count from account creation. Each D2–D4 month with the instance running 24 hours moves every date
earlier by about 9 days.

## 4. GitHub Actions

GitHub Pro (through the Student Developer Pack) includes **3,000 Actions minutes per month** for private
repositories. Standard runner list prices are $0.006 per minute for Linux x64 and $0.005 for Linux arm64
([runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing)); check how
included minutes are counted per runner type on that page. D1's CI has never run on GitHub, so minutes
per run are not yet measured. Images go to ECR, not GitHub Packages. Keep no payment method with a
non-zero Actions budget on the account.

## 5. Claude cost model

### 5.1 Prices (Exact, per million tokens, [pricing](https://platform.claude.com/docs/en/about-claude/pricing))

| Model | Input | 5-min cache write | Cache read | Output | Batch input / output |
|---|---|---|---|---|---|
| `claude-sonnet-5-5` | $2.00 | $2.50 | $0.10 | $10.00 | $1.00 / $5.00 |
| `claude-haiku-5-5` (prompts ≤ 100k tokens) | $0.10 | $0.125 | $0.01 | $0.50 | $0.05 / $0.25 |

Thinking tokens are billed as output. Prompt caching needs a prefix of at least 512 tokens on both models.

### 5.2 Measured payload sizes (characters, from `backend/evals/recorded/`)

| Role | Recordings | Input median / max | Output median / max | `max_tokens` (`agents/config.yaml`) |
|---|---|---|---|---|
| Intake | 22 | 1,043 / 1,308 | 373 / 397 | 2,048 |
| Planner | 3 | 10,863 / 11,642 | 1,828 / 1,831 | 2,048 |
| Critic | 11 | 14,169 / 14,208 | 2,289 / 2,289 | 1,024 |
| Explainer | 9 | 1,071 / 1,433 | 469 / 918 | 2,048 |

These were recorded with other models, carry no token counts, and the planner has only three samples.
The CP3 interview has no comparable recordings.

### 5.3 Formula

Per call: `input_tokens = characters / k + overhead`; `output_tokens = characters / k + thinking`;

`cost = Σ calls × (uncached_in × p_in + cached_in × p_read + cache_write × p_write + out × p_out) / 10⁶`

- `k` = characters per token. Anthropic's pricing page equates 1M tokens with about 2.5M Unicode
  characters (`k = 2.5`). Conservative scenarios use `k = 2.0`.
- `overhead` = 300 tokens per call for role framing and structured-output system content (assumed).
- Routing per [plan § 22.2](AWS_DEPLOYMENT_PLAN.md#222-model-routing-fixed).
- The pipeline makes one intake call, one planner call, at most two critic passes with one re-plan
  between them (`MAX_CRITIC_REPLAN_LOOPS = 2` in `agents/pipeline.py`), and one explainer call, plus at
  most one schema-repair retry per node.

### 5.4 Per-plan scenarios (Estimated)

| Scenario | Assumptions | Sonnet in / out tokens | Cost per plan | Plans on $25 | Plans on $50 |
|---|---|---|---|---|---|
| **Baseline** | Median sizes; `k` 2.5; one call per role; no thinking | 10,613 / 1,647 | **$0.0380** | 658 | 1,316 |
| **Conservative** | Max sizes; `k` 2.0; planner ×3 (two drafts plus one repair), critic ×2; +1,000 thinking tokens per Sonnet call | 33,171 / 10,036 | **$0.1672** | 150 | 299 |
| **Optimized** | Baseline with 70% of Sonnet input read from cache (ignores the one-time write premium) | 10,613 / 1,647 | **$0.0239** | 1,046 | 2,093 |
| Ceiling | 16 calls (intake 2, planner 6, critic 6, explainer 2), every output at `max_tokens` | 81,150 / 18,432 | $0.3511 | 71 | 142 |

Sonnet planner and critic calls are about 97% of baseline cost; the Haiku roles are below $0.001 per
plan. A prose refresh (one Haiku explainer call) costs about $0.0003.

### 5.5 Anthropic credit allocation ($50)

| Allocation | Amount | Expected runs (baseline / conservative) |
|---|---|---|
| Native integration and bounded live verification (L1) | $5 | Capped at 20 live runs (≈ $0.76 / $3.34) |
| Batch evaluation corpus | $10 | ≈ 526 batched baseline plans, run in small rounds |
| Controlled demo traffic | $25 | 658 / 150 |
| Acceptance and interview reserve | $10 | 263 / 60 |

Purchased Anthropic credits expire one year after purchase; check this grant's expiry in the Console.

## 6. Capacity estimates

**None of these is measured.** Each row states its formula or basis; D5's load test replaces them.

| Measure | Estimate | Basis |
|---|---|---|
| Registered accounts | **50** (beta cap) | Operator-issued invitations; a policy limit, not a capacity. Raised only per § 9. |
| Monthly active users | ≤ 50 | Bounded by registrations |
| Visitors (unauthenticated page views) | Origin-bound, not edge-bound | CloudFront's free 10 M requests ≈ 330,000 page views at ~30 requests each; uncached HTML and API calls reach one 2-vCPU origin whose throughput is unmeasured |
| Simultaneous browsing sessions | Unknown | D5 target: 20 concurrent scripted sessions with p95 below 1 s on non-LLM routes and no errors. A target, not a claim. |
| Simultaneous planning jobs | **2** (hard cap) | One worker process on ~2 GiB; further jobs get a typed busy response |
| Complete AI plans per day | **5.5** baseline, **1.25** conservative | Global ceiling: `plans/day = A / (D × c)`, with A = $25 demo allocation, D = 120 public days, c = cost per plan |
| Heavy re-planning users | Bounded by quota | Itinerary edits recompute deterministically without an LLM; only a new full plan or a prose refresh spends credit |

With 50 users and a quota of 2 full plans per user per day, the **global daily ceiling binds first**.
Once it is reached, the product returns the typed degraded response (deterministic planner plus template
explanation).

## 7. Hard runtime controls

All are D4 or L1 work; none exists today.

| Control | Planned initial value | Enforced by |
|---|---|---|
| Per-user daily full-plan quota | 2 | Durable counter in SQLite |
| Per-user daily prose-refresh quota | 10 | Durable counter |
| Global daily Claude cost ceiling | $0.21 (= $25 / 120 days) | Usage ledger, checked before each call |
| Global lifetime Claude ceiling | The demo allocation | Usage ledger |
| Maximum concurrent planning jobs | 2 | Job manager |
| Maximum LLM calls per plan | The spec 03 bound (no new call sites) | Existing per-request ceiling, lowered from the default 25 |
| Maximum output tokens per role | `agents/config.yaml`, raised only where thinking is enabled | Request parameters |
| Typed degraded response | Deterministic planner fallback + template explainer | Existing fallback paths |
| Kill switch | One environment flag that disables every LLM call | Startup and per-call check |
| Anthropic structural stop | Prepaid credit, auto-reload off | Anthropic billing |

## 8. Load-test plan

Run at D5 against the deployed stack with the LLM client in replay or scripted mode, so the test spends
no Anthropic credit. Measure real token use with a separate, budgeted set of live plans.

1. **Pages and API:** ramp scripted sessions from 1 to 50 over 15 minutes through CloudFront (sign-in,
   wallet, planning wizard, results), then hold for 30 minutes.
2. **Planning jobs:** submit 1, 2, and 4 concurrent jobs; confirm the cap returns typed busy responses
   above 2 and no job is lost while the process stays up.
3. **Write contention:** concurrent wallet edits and session saves at 10 and 25 writers.
4. **Restart under load:** restart the stack mid-test; confirm the documented job loss and recovery.

Metrics to capture before raising any limit:

| Metric | Threshold to raise a limit |
|---|---|
| Peak host memory | Below 75%, swap-in near zero |
| CPU and CPU-credit balance | Average below 60%; credit balance not trending to zero |
| Request latency | p95 below 1 s on non-LLM routes |
| Planning-job duration | p95 recorded; no timeouts |
| SQLite write contention | No busy or locked errors |
| Queue depth | Returns to zero after each burst |
| Error rate | Below 0.5% |
| Claude tokens and cost per completed plan | Within the conservative scenario |

## 9. Raising limits

Change one limit at a time, after at least 7 days of metrics inside every § 8 threshold, and recompute
§ 6 with the measured cost per plan. Raising the beta cap above 50 also requires re-running the load test
at the new target. A limit whose measured value approaches a
[scaling trigger](AWS_DEPLOYMENT_PLAN.md#25-triggers-for-the-scaling-milestone) is held, not raised.
