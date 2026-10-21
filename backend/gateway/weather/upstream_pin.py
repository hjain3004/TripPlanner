"""Pin data for the one audited upstream MCP server (G4).

Pure constants — no I/O. The adapter talks to exactly this server, at exactly
this version, started from a tree that matches exactly this lockfile. Bumping
any value here is a deliberate, reviewed change that must re-run the audit in
``reports/g4_open_meteo_weather_context.md`` (source diff, licence, dependency
tree, install scripts, network behaviour).
"""

from __future__ import annotations

from pathlib import Path

UPSTREAM_PACKAGE = "@cyanheads/open-meteo-mcp-server"
UPSTREAM_VERSION = "0.4.1"
UPSTREAM_REPO = "https://github.com/cyanheads/open-meteo-mcp-server"
UPSTREAM_COMMIT = "bff522070d90cdf99579a3d23a88e8c0e93324ee"
UPSTREAM_LICENSE = "Apache-2.0"
# npm's integrity for the published tarball (matches the audited lockfile entry).
UPSTREAM_TARBALL_INTEGRITY = (
    "sha512-fmWOH7NeOvJc1W84ylMdm19/pj6AVJoROHajE4cB7JknhP1/U/TFAFNnHFQyUeCPaRLeVzkVatD0I/"
    "UyMpwiSg=="
)
# The server's package.json "engines": node >= 24 (and bun >= 1.4 for its own scripts).
REQUIRED_NODE_MAJOR = 24

AUDITED_LOCKFILE = Path(__file__).parent / "upstream" / "package-lock.audited.json"
AUDITED_LOCKFILE_SHA256 = "b890ea08fed5fbda60b58e27dbe4078e069b0ae5fd491fc3613f5836b4b3cc12"
AUDITED_PACKAGE_COUNT = 48  # including the server itself; 0 with install scripts

# The server reads these (and only these) base-URL variables. They are pinned to
# the official defaults and never taken from the caller or the parent process.
OFFICIAL_BASE_URLS: dict[str, str] = {
    "OPEN_METEO_API_BASE_URL": "https://api.open-meteo.com",
    "OPEN_METEO_ARCHIVE_BASE_URL": "https://archive-api.open-meteo.com",
    "OPEN_METEO_MARINE_BASE_URL": "https://marine-api.open-meteo.com",
    "OPEN_METEO_AIR_QUALITY_BASE_URL": "https://air-quality-api.open-meteo.com",
    "OPEN_METEO_GEOCODING_BASE_URL": "https://geocoding-api.open-meteo.com",
    "OPEN_METEO_ENSEMBLE_BASE_URL": "https://ensemble-api.open-meteo.com",
    "OPEN_METEO_FLOOD_BASE_URL": "https://flood-api.open-meteo.com",
    "OPEN_METEO_CLIMATE_BASE_URL": "https://climate-api.open-meteo.com",
}
# Storage features stay off: no DataCanvas/DuckDB, no dataframe drop.
FIXED_SERVER_ENV: dict[str, str] = {
    "MCP_TRANSPORT_TYPE": "stdio",
    "NODE_ENV": "production",
    "CANVAS_PROVIDER_TYPE": "none",
    "OPENMETEO_DATAFRAME_DROP_ENABLED": "false",
    **OFFICIAL_BASE_URLS,
}
