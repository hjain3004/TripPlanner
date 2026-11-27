#!/usr/bin/env bash
# One scheduled pass of the recurring welcome-offer collection, using the existing entry point
# (`python -m ingestion.review_server recurring-run`). It is a thin, auditable wrapper:
#
#   * It does NOT enable anything by being installed. Live Firecrawl spending needs the owner to
#     set TRIPWISE_RECURRING_LIVE=1 in the environment file; without it the pass runs against
#     retained captures only (TRIPWISE_RECURRING_MANIFEST) and spends nothing.
#   * Overlap, slot idempotence, the credit limits and the lifetime allowance are enforced by the
#     command itself and its database, not by this script.
#   * The Firecrawl credential is read from the environment (FIRECRAWL_API_KEY) and is never
#     written anywhere by this script.
#
# Usage:  deploy/recurring-ingestion/run.sh /path/to/recurring.env
set -euo pipefail

ENV_FILE="${1:?usage: run.sh /path/to/recurring.env}"
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

: "${TRIPWISE_RECURRING_DATA_DIR:?the private ingestion data directory}"
: "${TRIPWISE_RECURRING_POLICIES:?source policies YAML}"
: "${TRIPWISE_RECURRING_WATCHLIST:?watchlist YAML}"
: "${TRIPWISE_RECURRING_WELCOME_TARGETS:?welcome targets YAML}"
: "${TRIPWISE_RECURRING_LIFETIME_CREDITS:?lifetime credit allowance (a hard ceiling)}"
: "${TRIPWISE_RECURRING_OPENING_CREDITS_USED:?credits used before this ledger existed}"
BACKEND="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../backend" && pwd)"
PY="${TRIPWISE_RECURRING_PYTHON:-$BACKEND/.venv/bin/python}"

args=(
  recurring-run
  --data-dir "$TRIPWISE_RECURRING_DATA_DIR"
  --source-policies "$TRIPWISE_RECURRING_POLICIES"
  --watchlist "$TRIPWISE_RECURRING_WATCHLIST"
  --welcome-targets "$TRIPWISE_RECURRING_WELCOME_TARGETS"
  --lifetime-credits "$TRIPWISE_RECURRING_LIFETIME_CREDITS"
  --opening-credits-used "$TRIPWISE_RECURRING_OPENING_CREDITS_USED"
  --limit "${TRIPWISE_RECURRING_LIMIT:-3}"
  --per-request-credits 5
  --per-run-credits "${TRIPWISE_RECURRING_PER_RUN_CREDITS:-12}"
  --per-month-credits "${TRIPWISE_RECURRING_PER_MONTH_CREDITS:-60}"
  --timeout-seconds 60
  --run-id "recurring-$(date -u +%Y%m)"
)
[ -n "${TRIPWISE_RECURRING_PUBLISHED_CATALOG:-}" ] \
  && args+=(--published-welcome-catalog "$TRIPWISE_RECURRING_PUBLISHED_CATALOG")

if [ "${TRIPWISE_RECURRING_LIVE:-0}" = "1" ]; then
  : "${FIRECRAWL_API_KEY:?live mode needs FIRECRAWL_API_KEY in the environment}"
  : "${TRIPWISE_RECURRING_ROBOTS_FILE:?live mode needs an offline robots file}"
  : "${TRIPWISE_RECURRING_RETAIN_DIR:?live mode keeps every complete response privately}"
  args+=(--live-firecrawl --confirm-no-overage
         --robots-file "$TRIPWISE_RECURRING_ROBOTS_FILE"
         --retain-responses-dir "$TRIPWISE_RECURRING_RETAIN_DIR")
else
  : "${TRIPWISE_RECURRING_MANIFEST:?offline mode needs --retained-captures-manifest}"
  args+=(--retained-captures-manifest "$TRIPWISE_RECURRING_MANIFEST")
fi

cd "$BACKEND"
exec "$PY" -m ingestion.review_server "${args[@]}"
