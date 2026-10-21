#!/usr/bin/env bash
# Fail when the committed API contract or the generated frontend client drift from the
# backend. Read-only with respect to the repository: everything is generated into a
# temporary directory and compared; nothing is written back to the branch.
#
#   scripts/check-contract-drift.sh
#   PY=/abs/python scripts/check-contract-drift.sh      # override the backend interpreter
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-$ROOT/backend/.venv/bin/python}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== OpenAPI: export twice, prove determinism"
( cd "$ROOT/backend" && "$PY" -m api.main --export-schema "$TMP/openapi_1.json" >/dev/null )
( cd "$ROOT/backend" && "$PY" -m api.main --export-schema "$TMP/openapi_2.json" >/dev/null )
cmp "$TMP/openapi_1.json" "$TMP/openapi_2.json" \
  || { echo "FAIL: two consecutive OpenAPI exports differ (non-deterministic schema)"; exit 1; }

echo "== OpenAPI: committed contract/openapi.json must equal the export (+ one trailing newline)"
cp "$TMP/openapi_1.json" "$TMP/expected.json"
printf '\n' >> "$TMP/expected.json"
if ! cmp -s "$TMP/expected.json" "$ROOT/contract/openapi.json"; then
  echo "FAIL: contract/openapi.json is out of date with the backend."
  echo "      Regenerate it, then the client (cd frontend && npm run gen:api), then the MSW"
  echo "      fixtures, and commit all of them together (spec 12 section 8)."
  diff <(python3 -m json.tool "$TMP/expected.json") <(python3 -m json.tool "$ROOT/contract/openapi.json") | head -40 || true
  exit 1
fi

echo "== Generated client: regenerate twice into a temp dir, prove stability and no drift"
cd "$ROOT/frontend"
GEN=(npx --no-install @hey-api/openapi-ts -i ../contract/openapi.json -c @hey-api/client-fetch)
"${GEN[@]}" -o "$TMP/client_1" >/dev/null
"${GEN[@]}" -o "$TMP/client_2" >/dev/null
diff -r "$TMP/client_1" "$TMP/client_2" >/dev/null \
  || { echo "FAIL: two consecutive client generations differ"; exit 1; }
if ! diff -r "$TMP/client_1" "$ROOT/frontend/src/lib/api/generated" >/dev/null; then
  echo "FAIL: frontend/src/lib/api/generated is out of date with contract/openapi.json."
  diff -r "$TMP/client_1" "$ROOT/frontend/src/lib/api/generated" | head -40 || true
  exit 1
fi

echo "CONTRACT_DRIFT_OK (openapi + generated client are deterministic and in sync)"
