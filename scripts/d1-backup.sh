#!/usr/bin/env bash
# Consistent backup of the irreplaceable application data (accounts, wallets, planning
# sessions, audit events) from a running stack, using SQLite's online-backup API - the
# only safe way to copy a database that is being written. Never `cp` a live .sqlite file.
#
#   scripts/d1-backup.sh [OUTPUT_DIR]          # default: ./backups
#   COMPOSE_PROJECT=tripwise-d1 scripts/d1-backup.sh
#
# tripwise.sqlite (the reference knowledge base) is NOT backed up: it is rebuilt from the
# seeds baked into the image on every start. See docs/DEPLOYMENT.md - 'Backups'.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${COMPOSE_PROJECT:-tripwise-d1}"
OUT="${1:-$ROOT/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"

CID="$(docker compose -p "$PROJECT" -f "$ROOT/deploy/compose.yaml" ps -q backend)"
[ -n "$CID" ] || { echo "no running backend container for project $PROJECT" >&2; exit 1; }

# Write inside the container's writable tmpfs, verify, then copy out.
docker exec -i "$CID" python - <<'PY'
import sqlite3
src = sqlite3.connect("file:/data/accounts.sqlite?mode=ro", uri=True)
dst = sqlite3.connect("/tmp/accounts.backup.sqlite")
src.backup(dst)
dst.close()
check = sqlite3.connect("/tmp/accounts.backup.sqlite")
assert check.execute("PRAGMA integrity_check").fetchone() == ("ok",), "integrity_check failed"
users = check.execute("SELECT COUNT(*) FROM users").fetchone()[0]
print(f"backup verified: integrity ok, {users} users")
PY
# `docker cp` cannot read a container tmpfs, so stream the verified file out instead.
docker exec "$CID" cat /tmp/accounts.backup.sqlite > "$OUT/accounts-$STAMP.sqlite"
docker exec "$CID" rm -f /tmp/accounts.backup.sqlite
chmod 600 "$OUT/accounts-$STAMP.sqlite"
echo "wrote $OUT/accounts-$STAMP.sqlite (contains user data: protect it like a credential)"
