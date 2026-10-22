# AWS operations runbook (planned — not yet executed against AWS)

**Status:** NOT YET EXECUTED AGAINST AWS. Every procedure below is a plan written on 2026-10-22. None
has been run, and each needs real-world validation the first time it is performed; procedures marked
**[V]** carry a specific open question that must be answered then. Record the outcome, timing, and any
correction in the milestone report, and fix this runbook in the same change.

Architecture and reasoning: [AWS_DEPLOYMENT_PLAN.md](AWS_DEPLOYMENT_PLAN.md). Cost figures and
checkpoints: [AWS_COST_AND_CAPACITY.md](AWS_COST_AND_CAPACITY.md). Local stack behaviour, environment
variables, health checks, and the D1 backup script: [DEPLOYMENT.md](DEPLOYMENT.md) — this runbook
links to it rather than repeating it.

## Conventions

- Placeholders: `<account-id>`, `<your-domain>`, `<owner>/<repo>`, `<instance-id>`, `<digest>`,
  `<STAMP>`, `<bucket>`, `<elastic-ip>`. Never write a real value into this repository.
- Region: `us-east-1` unless stated.
- **Secrets:** no command may print, persist, or commit a secret. Never run
  `aws ssm get-parameter --with-decryption` in a terminal or an SSM session. Never pass a secret as a
  command-line argument. Enter secret values in the AWS or Anthropic console.
- **Destructive steps** (`delete`, `terminate`, `destroy`) appear only in teardown and incident
  procedures, and a human runs them after reading the target.
- Each procedure ends with a **Verify** step: the check to run and the expected observation.

---

## 1. Account bootstrap (D2)

Prerequisite: the human has chosen Profile P or F
([plan § 4](AWS_DEPLOYMENT_PLAN.md#4-spend-controls-and-account-profiles)) and, for P, recorded the
approval and the accepted residual risk in `DEVIATIONS.md`.

1. Create a new, standalone account and select the **Paid** plan (Profile P) or the **Free** plan
   (Profile F). Do not join AWS Organizations, set up Control Tower, or enable IAM Identity Center's
   organization instance: on Profile F each upgrades the account to Paid.
2. **Root user:** enable MFA; create no root access keys; store root credentials offline; sign out.
3. **Alternate contacts** (Account settings): billing, operations, and security contacts set to an
   address the human monitors.
4. **Administrator:** one IAM user with console access only, MFA required, no access keys, the AWS
   managed `AdministratorAccess` policy plus the guardrail deny policy (plan § 4.2).
5. **Encryption:** in `us-east-1`, turn on EBS encryption by default.
6. Profile P: redeem the promotional credit on the Billing console's Credits page. Profile F: note the
   plan end date shown on the Billing home page.

**Verify:** the Billing console shows the expected plan and credit balances; the IAM credential report
shows root MFA enabled and no root access keys; `aws ec2 get-ebs-encryption-by-default` returns `true`.

**[V]** How the administrator gets short-lived CLI credentials without access keys: run Terraform in AWS
CloudShell under the MFA-authenticated console session, or use the AWS CLI's console-credential sign-in
if the installed version supports it. Choose one and record it.

## 2. Budget and credit notifications (D2)

1. **Notification budgets** (Billing → Budgets):
   - Monthly cost budget on spend **net of credits**, alert at $0.01 actual.
   - Monthly cost budget on **gross** spend, forecast alert at the planned monthly figure.
   - Credit-burn alerts at 50%, 75%, and 90% of the $125 allocation.
2. **Profile P only — budget action:** on the net-of-credit budget, add an action that stops
   `<instance-id>` when actual spend exceeds $1.
3. Put the checkpoint dates (days 120, 150, 165) and the teardown date in a calendar outside AWS.

**Verify:** the Budgets page lists each budget; alert subscriptions are confirmed by email. Budgets refresh
up to three times a day, so an alert can arrive hours after the spend. A budget is not a spending cap.

**[V]** The console option that includes or excludes credits from a budget's cost calculation.

## 3. Terraform state bootstrap (D2)

1. Create the state bucket `<bucket>-tfstate` once, outside Terraform: Block Public Access on,
   versioning on, SSE-S3 default encryption, a policy that denies non-TLS requests and allows only the
   administrator.
2. Configure the S3 backend with native lock files:

```hcl
terraform {
  backend "s3" {
    bucket       = "<bucket>-tfstate"
    key          = "tripwise/prod.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
```

**Verify:** `terraform init` succeeds; `terraform plan` on an empty configuration shows no changes; a
second concurrent `plan` reports the lock.

**[V]** Confirm `use_lockfile` against HashiCorp's S3 backend documentation for the Terraform version in
use.

## 4. GitHub OIDC bootstrap and deploy role (D3)

1. Terraform creates the IAM OIDC provider for `https://token.actions.githubusercontent.com` with
   audience `sts.amazonaws.com`.
2. Determine the repository's real subject format before writing the trust policy, from the repository's
   OIDC customization settings and GitHub's documentation. Repositories created after 2026-07-15 may use
   immutable subject claims.
3. Trust policy, `StringEquals`: `token.actions.githubusercontent.com:aud` = `sts.amazonaws.com`;
   `token.actions.githubusercontent.com:sub` = the `production`-environment subject from step 2.
4. Deploy role permissions, and nothing else:
   - `ecr:GetAuthorizationToken`; push and pull actions on the two repositories.
   - `ssm:SendCommand` on the deploy document ARN and on instances tagged `tripwise:role=app`.
   - `ssm:GetCommandInvocation`, `ssm:ListCommandInvocations`.
5. In GitHub, create the `production` environment restricted to `main`. Store the role ARN as an
   environment variable (it is not sensitive).

**Verify:** a dispatched workflow assumes the role (`aws sts get-caller-identity` prints the role ARN);
the same role receives `AccessDenied` for `ec2:RunInstances`, `ssm:GetParameter`, and `s3:DeleteObject`.

## 5. ECR (D3)

1. Repositories `tripwise-backend` and `tripwise-frontend`: private, tag immutability on.
2. Lifecycle policy: untagged images expire after 1 day; keep the 5 most recent tagged images.

**Verify:** `aws ecr describe-repositories` shows `imageTagMutability: IMMUTABLE`; pushing an existing
tag again fails.

## 6. EC2, EBS, S3 (D2–D3)

1. **Network:** one VPC, one public subnet, an internet gateway; security group `tripwise-origin` with
   **no inbound rules** until D5 and outbound TCP 443 only.
2. **Instance:** the type chosen by the selection gate (plan § 9); Amazon Linux 2023; standard CPU-credit
   mode; IMDSv2 required; no key pair; tag `tripwise:role=app`; an instance profile with
   `AmazonSSMManagedInstanceCore`, the CloudWatch agent policy, `s3:PutObject` on
   `arn:aws:s3:::<bucket>-backups/backups/*`, read access to `/tripwise/prod/*` parameters, and ECR pull.
3. **Volumes:** 20 GiB gp3 root; 10 GiB gp3 data volume mounted at `/srv/tripwise/data` by UUID in
   `/etc/fstab` with `nofail`, owner `10001:10001`, mode 700.
4. **Swap:** a 1 GiB swap file on the root volume.
5. **Backups bucket** `<bucket>-backups`: Block Public Access on, versioning on, SSE-S3, TLS-only policy,
   lifecycle (noncurrent versions after 30 days, current backups after 60 days).
6. **Snapshots:** a Data Lifecycle Manager policy on the data volume's tag, daily, keep 7.
7. **Elastic IP** attached to the instance.

**Verify:** `aws ec2 describe-instances --instance-ids <instance-id> --query "Reservations[].Instances[].MetadataOptions.HttpTokens"`
returns `required`; `aws ec2 describe-security-groups --group-names tripwise-origin` shows no ingress
rules; `findmnt /srv/tripwise/data` on the host shows the data volume.

## 7. Systems Manager access (D2)

1. Start a session: `aws ssm start-session --target <instance-id>` (needs the Session Manager plugin).
2. Send session logs to CloudWatch Logs with 14-day retention.
3. Install Docker and the Compose plugin; enable Docker at boot.

**Verify:** `aws ssm describe-instance-information` lists `<instance-id>` as `Online`; no TCP 22 rule
exists; `docker compose version` succeeds in the session.

## 8. Private staging deployment (D2)

Before ECR delivery exists, build on the instance from the commit under test:

1. Clone the repository on the host and check out the commit by SHA.
2. Build: `docker compose -p tripwise -f deploy/compose.yaml build` (on Graviton, a native
   `linux/arm64` build).
3. Start and check health per [DEPLOYMENT.md § 2](DEPLOYMENT.md#2-clean-clone-startup) and
   [§ 8](DEPLOYMENT.md#8-health-checks); run `make d1-smoke`.
4. Measure memory under a scripted planning workload: `docker stats --no-stream`, `free -m`, `vmstat 5`.
5. Reach the site from the administrator's machine through an SSM port-forwarding session, never a
   public port.

**Verify:** the smoke prints its success marker; readiness reports sample mode; memory figures are
recorded for the plan § 9 decision.

## 9. Deploy by immutable digest (D3 onward)

The deploy workflow (`workflow_dispatch`, environment `production`) passes two digests to the SSM deploy
document. On the host the document runs these steps in order and stops at the first failure:

1. Record the running digests in `/srv/tripwise/deploy/previous`.
2. **Pre-deployment backup** (§ 13, steps 1–3). Abort the deploy if it fails.
3. Pull `<account-id>.dkr.ecr.us-east-1.amazonaws.com/tripwise-backend@sha256:<digest>` and the
   frontend equivalent.
4. Write the overlay's image references; `docker compose … up -d --wait`.
5. Health: nginx `/healthz` and backend `/health/ready` ([DEPLOYMENT.md § 8](DEPLOYMENT.md#8-health-checks)).
6. Smoke: register a throwaway account, sign in, read the wallet, sign out, delete the account.
7. On any failure in steps 4–6, run § 10 and report the deploy as failed.

**Verify:** the workflow log shows both digests; `docker inspect --format '{{.Image}}'` on each container
matches; the SSM command status is `Success`.

**Expected effect:** the site is unavailable during the restart and in-flight planning jobs are lost (§ 15).

## 10. Rollback to the previous digest

1. Read `/srv/tripwise/deploy/previous`.
2. If the failed release changed the database schema, restore the pre-deployment backup (§ 14) first.
   The accounts store uses additive migrations; check the release notes regardless.
3. Point the overlay at the previous digests; `docker compose … up -d --wait`.
4. Health and smoke as in § 9.

**Verify:** running digests equal the recorded previous ones; smoke passes.

## 11. Reboot recovery

1. `aws ec2 reboot-instances --instance-ids <instance-id>`, or observe an unplanned reboot.
2. Wait for SSM `Online`; systemd starts Docker and the stack.

**Verify:** readiness passes without intervention; a known account still signs in; a planning job created
before the reboot returns 404 (expected, § 15). If the data volume did not mount, `findmnt` shows nothing
and readiness fails: mount it, then restart the stack.

## 12. Public edge (D5; requires explicit human approval for public deployment)

1. **DNS:** create the Route 53 public hosted zone for `<your-domain>`; set the registrar's name servers
   to the zone's four name servers.
2. **Viewer certificate:** request a public ACM certificate in `us-east-1` for `<your-domain>` and
   `www.<your-domain>`; validate through DNS.
3. **Origin certificate:** create `origin.<your-domain>` → `<elastic-ip>`. Obtain the ACME DNS-01
   certificate with permissions limited to the `_acme-challenge.origin` record; install it for nginx;
   schedule renewal. **[V]** The Route 53 IAM condition keys that restrict which records can change.
4. **Origin header secret:** create it as a `SecureString` in the Parameter Store console; the deploy
   script writes it into nginx's environment; Terraform reads it for the distribution.
5. **Distribution:** origin `origin.<your-domain>`, HTTPS only; viewer HTTP redirected to HTTPS; cache
   behaviours per [plan § 18](AWS_DEPLOYMENT_PLAN.md#18-edge-route-53-cloudfront-acm-origin-restriction-caching);
   forward `CloudFront-Viewer-Address`; attach the custom origin header. Try subscribing to the
   flat-rate Free plan in the console; if refused, stay on pay-as-you-go and record the reason.
6. **Open the origin:** add the only inbound rule — TCP 443 from prefix list
   `com.amazonaws.global.cloudfront.origin-facing`.
7. Create ALIAS records for `<your-domain>` and `www.<your-domain>` → the distribution.

**Verify:**
- `curl -sI https://<your-domain>/` → `200` through CloudFront.
- `curl -sI http://<your-domain>/` → redirect to HTTPS.
- `curl -sk --max-time 5 https://<elastic-ip>/` from outside AWS → timeout.
- A request reaching nginx without the origin header → `403`.
- `/api/*` and HTML responses are never cache hits; `/_next/static/*` is a hit on repeat.

## 13. SQLite backup to S3

Adapts `scripts/d1-backup.sh` ([DEPLOYMENT.md § 12](DEPLOYMENT.md#12-backups)):

1. Run the online backup into a root-owned, mode-700 staging directory on the host. Never copy the live
   file.
2. Confirm the integrity check passed and the SHA-256 of the copy matches.
3. `aws s3 cp accounts-<STAMP>.sqlite s3://<bucket>-backups/backups/ --sse AES256`, with the SHA-256 as
   object metadata; then delete the local copy.
4. A systemd timer runs steps 1–3 every 6 hours; the deploy document runs them before each deploy.
5. On success, publish the custom metric `BackupSucceeded=1`; the "no backup in 8 hours" alarm watches it.

**Verify:** the alarm is `OK`; the administrator (the instance role cannot list) sees the newest object in
`s3://<bucket>-backups/backups/` is under 6 hours old.

## 14. SQLite restore

Run as the administrator; follows [DEPLOYMENT.md § 12](DEPLOYMENT.md#12-backups).

1. Choose the backup (latest, or a specific `<STAMP>`) and download it to the host's staging directory
   through the restore role.
2. Check its SHA-256 against the object metadata and run `PRAGMA integrity_check` in a one-off container.
   Stop if either fails.
3. Stop the stack: `docker compose … stop`.
4. Move the current `accounts.sqlite` and any journal file aside; do not delete them yet.
5. Copy the backup in with a one-off root container that sets owner `10001:10001` and mode 600.
6. Start: `docker compose … up -d --wait`.

**Verify:** readiness passes; a known account signs in; elapsed time is recorded against the 60-minute RTO
target. Delete the moved-aside files only after the human confirms the restore.

**From a snapshot:** create a volume from the latest data-volume snapshot, attach it, mount it read-only at
a test path, run the integrity check, then use that file in step 5.

## 15. Lost process-local jobs (expected behaviour)

Planning jobs live in one process's memory. A restart, deploy, rollback, or reboot loses them, and their
status endpoint returns 404
([DEPLOYMENT.md § 9](DEPLOYMENT.md#9-restart-behaviour-measured-by-the-smoke-not-assumed)). Accounts,
wallets, saved trips, and planning sessions persist in SQLite. **Response:** none needed; users start the
plan again. Deploy at low traffic and tell invited users about planned windows. Frequent recurrence is a
scaling trigger (plan § 25).

## 16. Claude API key rotation and revocation (L1 onward)

**Rotation (scheduled, or on any suspicion):**

1. Create a new key in the Anthropic Console, in the TripWise workspace.
2. Update `/tripwise/prod/anthropic_api_key` in the Parameter Store console.
3. Redeploy the current digests (§ 9) so the stack reads the new value.
4. Run one bounded live plan and confirm a new ledger row.
5. Disable the old key in the Console.

**Revocation (suspected leak):** disable the key in the Console **first**, then set the application kill
switch (§ 17), then rotate. Compare the Console's usage page with the ledger for unexplained calls.

**Verify:** the old key is no longer active in the Console; the ledger shows calls only after the redeploy.

## 17. Anthropic kill switch

Two independent stops:

1. **Application:** set the LLM kill-switch flag (its name is fixed in L1) under the parameter path and
   redeploy the current digests. LLM-backed routes return the typed degraded response (deterministic
   planner plus template explanation).
2. **Provider:** disable the API key in the Anthropic Console. With auto-reload off, a zero balance stops
   calls the same way.

**Verify:** a test plan completes in degraded mode; the ledger shows no new rows.

## 18. Disk pressure

Trigger: the data-volume (80%) or root-volume (85%) alarm.

1. In a session: `df -h /srv/tripwise/data /` and `du -sh /srv/tripwise/data/*`.
2. Data volume: the likely cause is `/data/traces`, which is unbounded until D4. Move old trace files off
   the host; never touch `accounts.sqlite` or its journal.
3. Root volume: `docker image prune` (removes only images no container uses); check log sizes.
4. If space cannot be freed: grow the gp3 volume (`aws ec2 modify-volume --volume-id … --size …`) and
   extend the filesystem. **[V]** The filesystem type and grow command on the chosen AMI.

**Verify:** usage below the threshold; the alarm returns to `OK`.

## 19. Excessive Claude spend

Trigger: the daily-cost alarm, a ledger anomaly, or the Console balance falling faster than planned.

1. Set the application kill switch (§ 17, step 1).
2. Query the ledger by role and hour: find the route, the role, and whether `max_tokens` or repeated calls
   are responsible. The ledger holds no prompt content; do not start logging it.
3. Check for abuse: requests per account and per client address in the nginx logs.
4. Fix the quota, ceiling, prompt, or routing through a normal change; then re-enable.

**Verify:** cost per completed plan is back within the conservative scenario in the
[cost model](AWS_COST_AND_CAPACITY.md#54-per-plan-scenarios-estimated).

## 20. Origin-header secret rotation

1. Create the new value in the Parameter Store console.
2. Deploy nginx accepting **both** the old and new values.
3. Change the distribution's custom header to the new value (`terraform apply`) and wait for it to deploy.
4. Deploy nginx accepting only the new value.

**Verify:** the site serves normally; a request carrying the old value receives 403.

## 21. Compromised instance (suspected)

1. **Contain:** remove the security group's inbound rule (the site goes offline); disable the Anthropic
   key (§ 16). Keep the instance running for evidence unless it is causing spend; then stop it.
2. **Preserve:** snapshot the root and data volumes and tag them `evidence`.
3. **Rotate:** the Anthropic key, the origin-header secret, and the ACME account key.
4. **Rebuild:** launch a new instance with Terraform; restore the latest backup taken **before** the
   suspected compromise (§ 14); deploy known-good digests. Restoring from an earlier backup also discards
   any sessions created after it.
5. **Review:** CloudTrail event history, the IAM credential report, ECR digests against CI records, and
   Billing for unexplained resources.
6. **Users:** if account data may have been read, tell invited users what happened and what was exposed.

**Verify:** the new instance serves known-good digests; no unexplained resources remain; the old instance
is terminated once the human confirms the evidence is no longer needed.

## 22. Final data export before the credit period ends

Run at day 150 and again at day 165 ([cost model § 3.3](AWS_COST_AND_CAPACITY.md#33-checkpoints)).

1. Take a fresh backup (§ 13); download it and the newest S3 object to an encrypted location outside AWS
   that the human controls.
2. Check SHA-256 and `PRAGMA integrity_check` on the downloaded copy; restore it into a local D1 stack
   ([DEPLOYMENT.md § 12](DEPLOYMENT.md#12-backups)) and sign in with a known account.
3. Export non-secret evidence: dashboard screenshots, drill timings, alarm history, the content-free usage
   ledger, Terraform outputs.
4. Offer invited users their privacy export before the end date.

**Verify:** the local restore passes smoke; evidence files are stored with the milestone report.

## 23. Full teardown

Run only after § 22 is verified and the human approves. Profile F accounts close six months after opening;
tear down earlier anyway, so nothing depends on that.

1. Disable the Anthropic key and set the kill switch.
2. Disable, then delete, the CloudFront distribution; delete the ALIAS records.
3. `terraform destroy` for the application stack. Read the plan output, which lists every resource,
   before confirming.
4. Check for anything outside Terraform: Elastic IPs, snapshots (including `evidence`), AMIs, ECR images,
   S3 objects and versions, CloudWatch log groups, Parameter Store parameters, the ACM certificate, the
   hosted zone.
5. Empty and delete the backups bucket (all versions) only after the off-AWS export is confirmed.
6. Delete the Terraform state bucket last.
7. Profile P: confirm in Billing that the forecast net of credits is $0.00, then close the account if no
   further use is planned.

**Verify:** Cost Explorer shows no new usage in the following days; Billing shows no new usage lines; the
off-AWS export still opens.
