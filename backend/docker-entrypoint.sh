#!/bin/sh
# Container entrypoint: validate -> seed -> serve. Uses the application's real startup path
# (api.runtime_config, core.db seed, and the accounts schema/migration path in the API
# lifespan); there is deliberately no second schema initialiser here.
set -eu

# 1. Required configuration. Failure prints variable NAMES only, never values.
python -m api.runtime_config

# 2. Rebuild the reference knowledge base from the seeds baked into this image, so the
#    data always matches the deployed code. It lives in its own database file: user
#    accounts, wallets and planning sessions (accounts.sqlite) are never touched.
python -m core.db seed

# 3. Exactly ONE worker. Planning jobs are held in process memory (api/job_manager.py) and
#    the databases are SQLite files, so this profile is single-instance by design.
exec uvicorn api.main:app \
    --host 0.0.0.0 --port 8000 \
    --workers 1 --no-server-header --timeout-graceful-shutdown 10
