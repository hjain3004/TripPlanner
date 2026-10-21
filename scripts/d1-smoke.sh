#!/usr/bin/env bash
# Genuine full-stack smoke against the production-like Compose stack.
#
#   scripts/d1-smoke.sh            # fresh stack -> phase 1 -> restart backend -> phase 2 -> teardown
#   scripts/d1-smoke.sh --keep     # leave the stack (and its data volume) running afterwards
#
# Uses its OWN Compose project (tripwise-d1-smoke) and port so it never touches a stack a
# developer already has running, and always starts from an empty data volume.
# Requires: Docker with Compose v2, Node (frontend deps installed, Chromium for Playwright).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROJECT="tripwise-d1-smoke"
PORT="${TRIPWISE_HTTP_PORT:-18080}"
KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1
COMPOSE=(docker compose -p "$PROJECT" -f deploy/compose.yaml)
STATE="$(mktemp "${TMPDIR:-/tmp}/d1-smoke-state.XXXXXX")"
LOGS="$(mktemp "${TMPDIR:-/tmp}/d1-smoke-logs.XXXXXX")"

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "---- smoke failed (exit $status); last backend/proxy logs ----"
    "${COMPOSE[@]}" logs --no-color --tail 40 backend proxy 2>/dev/null || true
  fi
  if [ "$KEEP" -eq 0 ]; then
    "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -f "$STATE" "$STATE.storage.json" "$LOGS"
}
trap cleanup EXIT

export TRIPWISE_HTTP_PORT="$PORT"
export TRIPWISE_STACK_URL="http://localhost:$PORT"
export TRIPWISE_SMOKE_STATE="$STATE"

wait_ready() {
  local deadline=$((SECONDS + 120))
  until curl -fsS "$TRIPWISE_STACK_URL/api/health/ready" >/dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "backend did not become ready within 120s" >&2
      return 1
    fi
    sleep 2
  done
}

echo "== 1/6 fresh stack (empty data volume)"
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
"${COMPOSE[@]}" up -d --build --wait

echo "== 2/6 stack topology facts"
BACKEND_ID="$("${COMPOSE[@]}" ps -q backend)"
echo "backend user: $(docker exec "$BACKEND_ID" id -u) (expected non-root 10001)"
[ "$(docker exec "$BACKEND_ID" id -u)" = "10001" ]
curl -fsS "$TRIPWISE_STACK_URL/api/health/ready"; echo
if docker exec "$BACKEND_ID" python -c "import urllib.request as u; u.urlopen('https://api.open-meteo.com', timeout=4)" >/dev/null 2>&1; then
  echo "FAIL: the backend container has outbound network access" >&2
  exit 1
fi
echo "backend has no outbound network access (no live provider can be reached)"

echo "== 3/6 phase 1: live frontend -> real backend journey"
( cd frontend && npx playwright test -c e2e/playwright.live-stack.config.ts --grep @phase1 )

echo "== 4/6 restart the BACKEND container (same data volume)"
"${COMPOSE[@]}" restart backend
wait_ready

echo "== 5/6 phase 2: persistence and honest limitations after restart"
( cd frontend && npx playwright test -c e2e/playwright.live-stack.config.ts --grep @phase2 )

echo "== 6/6 no secrets or database files leaked into the images"
for svc in backend frontend; do
  IMG="$("${COMPOSE[@]}" images -q "$svc" | head -n1)"
  if docker run --rm --entrypoint sh "$IMG" -c 'find / -xdev \( -name "*.sqlite" -o -name ".env" -o -name ".env.*" \) -not -path "/proc/*" 2>/dev/null | grep -v "^/data/" | head -5' | grep -q .; then
    echo "FAIL: database or env file found in the $svc image" >&2
    exit 1
  fi
done
echo "D1_SMOKE_OK"
