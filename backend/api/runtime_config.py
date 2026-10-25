"""Startup validation of genuinely required deployment configuration.

Only configuration whose absence or malformation would make the process unsafe or
unable to hold state is validated. Provider credentials are deliberately NOT
required: sample mode must start with none of them set.

Every message names a variable and a fixed problem - never a value - so a
misconfigured secret cannot be echoed into logs or an HTTP response.

Run as ``python -m api.runtime_config`` (the container entrypoint does) or let the
FastAPI lifespan call :func:`assert_valid_runtime_config`.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

ENV_NAME = "TRIPWISE_ENV"
_ENVIRONMENTS = frozenset({"development", "production"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})
# (provider id, enable flag, kill switch) for every provider that could ever be made live.
LIVE_PROVIDER_FLAGS: tuple[tuple[str, str, str], ...] = (
    ("gondola", "TRIPWISE_GONDOLA_LIVE_ENABLED", "TRIPWISE_GONDOLA_KILL_SWITCH"),
    ("open_meteo", "TRIPWISE_OPEN_METEO_ENABLED", "TRIPWISE_OPEN_METEO_KILL_SWITCH"),
)


@dataclass(frozen=True)
class ConfigIssue:
    variable: str
    problem: str


class ConfigError(RuntimeError):
    def __init__(self, issues: list[ConfigIssue]) -> None:
        self.issues = issues
        detail = "; ".join(f"{i.variable}: {i.problem}" for i in issues)
        super().__init__(f"invalid runtime configuration - {detail}")


def _truthy(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in _TRUTHY


def flagged_live_providers(env: Mapping[str, str] | None = None) -> list[str]:
    """Providers whose enable flag is set and not overridden by their kill switch.

    Flag-level only: this lets the API layer report activation state without
    importing a provider package.
    """
    source = os.environ if env is None else env
    return sorted(
        provider_id
        for provider_id, enable, kill in LIVE_PROVIDER_FLAGS
        if _truthy(source, enable) and not _truthy(source, kill)
    )


def _check_data_dir(raw: str) -> str | None:
    path = Path(raw)
    if not path.is_absolute():
        return "must be an absolute path"
    if not path.is_dir():
        return "must be an existing directory"
    try:
        with tempfile.TemporaryFile(dir=path):
            pass
    except OSError:
        return "must be writable by the application user"
    return None


def _check_origin(origin: str) -> bool:
    """An origin is scheme://host[:port] - no path (not even a trailing slash, which
    Starlette's exact-match CORS would never match), query, fragment or wildcard."""
    try:
        parsed = urlparse(origin)
        parsed.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError:
        return False
    return (
        origin.isascii()
        and parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and "*" not in origin
        and parsed.path == ""
        and not (parsed.params or parsed.query or parsed.fragment)
    )


def validate_runtime_config(env: Mapping[str, str] | None = None) -> list[ConfigIssue]:
    source = os.environ if env is None else env
    issues: list[ConfigIssue] = []

    mode = source.get(ENV_NAME, "").strip().lower()
    if mode and mode not in _ENVIRONMENTS:
        issues.append(ConfigIssue(ENV_NAME, "must be 'development' or 'production'"))
    production = mode == "production"

    data_dir = source.get("TRIPWISE_DATA_DIR", "").strip()
    if production and not data_dir:
        issues.append(ConfigIssue("TRIPWISE_DATA_DIR", "is required in production"))
    elif data_dir:
        problem = _check_data_dir(data_dir)
        if problem:
            issues.append(ConfigIssue("TRIPWISE_DATA_DIR", problem))

    origins = source.get("TRIPWISE_CORS_ORIGINS")
    if origins is not None:
        entries = [o.strip() for o in origins.split(",")]
        if not any(entries) or not all(_check_origin(o) for o in entries if o):
            issues.append(
                ConfigIssue(
                    "TRIPWISE_CORS_ORIGINS",
                    "must be a comma-separated list of http(s) origins without wildcards or paths",
                )
            )

    max_calls = source.get("TRIPWISE_LLM_MAX_CALLS")
    if max_calls is not None:
        text = max_calls.strip()
        if not (text.isascii() and text.isdigit()) or int(text) < 1:
            issues.append(ConfigIssue("TRIPWISE_LLM_MAX_CALLS", "must be a positive integer"))

    if production:
        flagged = flagged_live_providers(source)
        for provider_id, enable, _kill in LIVE_PROVIDER_FLAGS:
            if provider_id in flagged:
                issues.append(
                    ConfigIssue(
                        enable, "live providers are not activatable in the sample-mode profile"
                    )
                )
        # Other ways a live (network-reaching) capability would be switched on.
        if source.get("TRIPWISE_INTERVIEW_LLM_ZERO_SPEND_CONFIRMED", "").strip() == "1":
            issues.append(
                ConfigIssue(
                    "TRIPWISE_INTERVIEW_LLM_ZERO_SPEND_CONFIRMED",
                    "the hosted interview LLM role is not activatable in the sample-mode profile",
                )
            )
        if source.get("TRIPWISE_POST_PLAN_LLM_ZERO_SPEND_CONFIRMED", "").strip() == "1":
            issues.append(
                ConfigIssue(
                    "TRIPWISE_POST_PLAN_LLM_ZERO_SPEND_CONFIRMED",
                    "the hosted post-plan LLM role is not activatable in the sample-mode profile",
                )
            )
        if source.get("TRIPWISE_TRIPADVISOR_API_KEY", "").strip() and not _truthy(
            source, "TRIPWISE_TRIPADVISOR_KILL_SWITCH"
        ):
            issues.append(
                ConfigIssue(
                    "TRIPWISE_TRIPADVISOR_API_KEY",
                    "a Tripadvisor credential is not usable in the sample-mode profile",
                )
            )
    return issues


def assert_valid_runtime_config(env: Mapping[str, str] | None = None) -> None:
    issues = validate_runtime_config(env)
    if issues:
        raise ConfigError(issues)


def main() -> int:
    issues = validate_runtime_config()
    if not issues:
        return 0
    print("invalid runtime configuration:", file=sys.stderr)
    for issue in issues:
        print(f"  {issue.variable}: {issue.problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
