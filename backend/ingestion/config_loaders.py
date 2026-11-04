"""Validated loaders for the card-bank operator configuration files (spec 05 sections 0-1).

Three files, all local to the operator's data directory (they may name captured material, so
they are not committed to the repository):

* ``source_policies.yaml``  - ``SourcePolicyRecord`` entries, the terms-of-service record that
  must exist before any source is touched;
* ``discovery_sources.yaml`` - aggregator *lead* sources (spec 05 section 0). A lead says a card
  exists and which issuer page to read; it never carries a financial fact;
* ``watchlist.yaml`` - issuer pages the operator monitors, converted to ``WatchTarget``.

The loaders only read and validate. They never fetch, never write to the ingestion store and
never contact a network. Every problem in a file is collected and reported together as typed
``ConfigIssue`` records, so an operator can fix a file in one pass.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ingestion.contracts import PageKind, SourcePolicyRecord, WatchTarget, _https_url
from ingestion.preflight import SourcePreflight, canonicalize_url

MAX_CONFIG_BYTES = 1_048_576

# Aggregators named by spec 05 section 0 and the owner's 2026-11-01 source decisions. They are
# lead sources only: a source policy (a place facts may be captured from) can never name one,
# whether or not a discovery file is supplied. Subdomains match.
AGGREGATOR_DOMAINS: frozenset[str] = frozenset(
    {
        "bankbazaar.com",
        "cardexpert.in",
        "nerdwallet.com",
        "paisabazaar.com",
        "policybazaar.ae",
        "policybazaar.com",
        "thepointsguy.com",
        "yallacompare.com",
    }
)

_DOCUMENT_KINDS = {PageKind.CARD_PAGE, PageKind.OFFER_PAGE, PageKind.TNC_PDF}


class ConfigIssue(BaseModel):
    """One problem found in one configuration file."""

    code: str = Field(min_length=1)
    location: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ConfigValidationError(ValueError):
    """A configuration file was refused; ``issues`` lists every problem found."""

    def __init__(self, path: Path | None, issues: Iterable[ConfigIssue]) -> None:
        self.path = path
        self.issues = tuple(issues)
        first = self.issues[0] if self.issues else None
        summary = "invalid configuration" if first is None else f"{first.code}: {first.message}"
        extra = f" (+{len(self.issues) - 1} more)" if len(self.issues) > 1 else ""
        super().__init__(f"{path or 'configuration'}: {summary}{extra}")


def _issue(code: str, location: str, message: str) -> ConfigIssue:
    return ConfigIssue(code=code, location=location, message=message)


def read_structured(path: Path) -> Any:
    """Read one bounded JSON or YAML document (``.json``, ``.yaml``, ``.yml``)."""
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ConfigValidationError(
            path, [_issue("config_unreadable", "file", f"cannot read file: {error}")]
        ) from error
    if size > MAX_CONFIG_BYTES:
        raise ConfigValidationError(
            path,
            [_issue("config_too_large", "file", f"file exceeds {MAX_CONFIG_BYTES} bytes")],
        )
    suffix = path.suffix.lower()
    if suffix not in {".json", ".yaml", ".yml"}:
        raise ConfigValidationError(
            path,
            [_issue("config_unsupported_format", "file", "use a .json, .yaml or .yml file")],
        )
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigValidationError(
            path, [_issue("config_unreadable", "file", f"cannot read file: {error}")]
        ) from error
    except (ValueError, yaml.YAMLError) as error:
        raise ConfigValidationError(
            path, [_issue("config_invalid_syntax", "file", f"not valid {suffix[1:]}: {error}")]
        ) from error


def _entries(raw: Any, *, key: str, path: Path) -> list[Any]:
    """Accept a bare list, a ``{key: [...]}`` mapping, or one entry mapping."""
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict) and key in raw and set(raw) == {key} and isinstance(raw[key], list):
        entries = raw[key]
    elif isinstance(raw, dict) and key not in raw:
        entries = [raw]
    else:
        raise ConfigValidationError(
            path,
            [
                _issue(
                    "config_invalid_shape",
                    "file",
                    f"expected a list of entries or a mapping with only a '{key}' list",
                )
            ],
        )
    if not entries:
        raise ConfigValidationError(
            path, [_issue("config_invalid_shape", "file", "the file contains no entries")]
        )
    return entries


def _validation_issues(error: ValidationError, location: str) -> list[ConfigIssue]:
    return [
        _issue(
            "config_invalid_entry",
            location + "".join(f".{part}" for part in item["loc"]),
            str(item["msg"]),
        )
        for item in error.errors()
    ]


def _unknown_keys(
    entry: Mapping[str, Any], allowed: Iterable[str], location: str
) -> list[ConfigIssue]:
    permitted = set(allowed)
    return [
        _issue(
            "config_unknown_key",
            f"{location}.{key}",
            f"unknown key {key!r}; allowed keys are {sorted(permitted)}",
        )
        for key in sorted(map(str, entry), key=str)
        if key not in permitted
    ]


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def is_aggregator_host(host: str, *, extra_domains: Iterable[str] = ()) -> bool:
    """True when ``host`` is (a subdomain of) a known or configured aggregator."""
    candidates = {domain.lower().lstrip(".") for domain in (*AGGREGATOR_DOMAINS, *extra_domains)}
    return any(host == domain or host.endswith(f".{domain}") for domain in candidates)


# ----------------------------------------------------------------------------------------- #
# Source policies
# ----------------------------------------------------------------------------------------- #


def load_source_policies(
    path: Path, *, aggregator_domains: Iterable[str] = ()
) -> tuple[SourcePolicyRecord, ...]:
    """Load issuer source policies; refuse aggregator domains, duplicates and unknown keys."""
    entries = _entries(read_structured(path), key="source_policies", path=path)
    issues: list[ConfigIssue] = []
    policies: list[SourcePolicyRecord] = []
    seen: set[str] = set()
    extra = tuple(aggregator_domains)
    for index, entry in enumerate(entries):
        location = f"source_policies[{index}]"
        if not isinstance(entry, dict):
            issues.append(_issue("config_invalid_entry", location, "entry must be a mapping"))
            continue
        unknown = _unknown_keys(entry, SourcePolicyRecord.model_fields, location)
        if unknown:
            issues.extend(unknown)
            continue
        try:
            record = SourcePolicyRecord.model_validate(entry)
        except ValidationError as error:
            issues.extend(_validation_issues(error, location))
            continue
        domain = record.domain.strip().lower().lstrip(".")
        if "/" in domain or ":" in domain or domain != record.domain.strip().lower():
            issues.append(
                _issue(
                    "config_invalid_entry",
                    f"{location}.domain",
                    "domain must be a bare host name such as 'hdfc.bank.in'",
                )
            )
            continue
        if is_aggregator_host(domain, extra_domains=extra):
            issues.append(
                _issue(
                    "aggregator_domain",
                    f"{location}.domain",
                    f"{domain} is an aggregator: it can be a discovery lead source but never "
                    "a source of financial facts",
                )
            )
            continue
        if not (
            host_of(record.source_url) == domain
            or host_of(record.source_url).endswith(f".{domain}")
        ):
            issues.append(
                _issue(
                    "config_policy_violation",
                    f"{location}.source_url",
                    f"source_url host is outside the policy domain {domain}",
                )
            )
            continue
        if record.policy_id in seen:
            issues.append(
                _issue(
                    "config_duplicate_id",
                    f"{location}.policy_id",
                    f"duplicate {record.policy_id!r}",
                )
            )
            continue
        seen.add(record.policy_id)
        policies.append(record)
    if issues:
        raise ConfigValidationError(path, issues)
    return tuple(policies)


# ----------------------------------------------------------------------------------------- #
# Discovery sources (aggregator leads)
# ----------------------------------------------------------------------------------------- #


class DiscoverySource(BaseModel):
    """One aggregator lead source with its terms-of-service record (spec 05 section 0).

    Deliberately has no provenance and no field that could hold a financial value: a source
    says where leads may be read, nothing more.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    url: str
    corridor: Literal["IN", "AE", "US"]
    tos_url: str
    tos_read_on: date
    automated_access_permitted: bool
    manual_only: bool
    stated_rate_limit: str | None = None

    _urls = field_validator("url", "tos_url")(_https_url)

    @model_validator(mode="after")
    def _exactly_one_access_mode(self) -> DiscoverySource:
        if self.automated_access_permitted == self.manual_only:
            raise ValueError(
                "set exactly one of automated_access_permitted and manual_only: a source whose "
                "terms prohibit automation is manual_only"
            )
        return self

    @property
    def domain(self) -> str:
        return host_of(self.url)


def load_discovery_sources(path: Path, *, today: date | None = None) -> tuple[DiscoverySource, ...]:
    """Load ``discovery_sources.yaml``; every entry needs its terms record."""
    entries = _entries(read_structured(path), key="discovery_sources", path=path)
    issues: list[ConfigIssue] = []
    sources: list[DiscoverySource] = []
    names: set[str] = set()
    for index, entry in enumerate(entries):
        location = f"discovery_sources[{index}]"
        if not isinstance(entry, dict):
            issues.append(_issue("config_invalid_entry", location, "entry must be a mapping"))
            continue
        unknown = _unknown_keys(entry, DiscoverySource.model_fields, location)
        if unknown:
            issues.extend(unknown)
            continue
        try:
            source = DiscoverySource.model_validate(entry)
        except ValidationError as error:
            issues.extend(_validation_issues(error, location))
            continue
        if today is not None and source.tos_read_on > today:
            issues.append(
                _issue(
                    "config_invalid_entry",
                    f"{location}.tos_read_on",
                    "the terms cannot have been read in the future",
                )
            )
            continue
        if source.name in names:
            issues.append(
                _issue("config_duplicate_id", f"{location}.name", f"duplicate {source.name!r}")
            )
            continue
        names.add(source.name)
        sources.append(source)
    if issues:
        raise ConfigValidationError(path, issues)
    return tuple(sources)


# ----------------------------------------------------------------------------------------- #
# Watchlist
# ----------------------------------------------------------------------------------------- #


class WatchlistEntry(BaseModel):
    """A ``watchlist.yaml`` entry (spec 05 section 1) plus the ids the contracts need."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(min_length=1)
    url: str
    kind: PageKind
    target: str | tuple[str, ...]
    source_policy_id: str = Field(min_length=1)
    check_frequency_days: int = Field(ge=1)
    css_hint: str | None = None
    backend: Literal["local", "firecrawl", "manual"] = "local"
    manual_only: bool = False

    _url = field_validator("url")(_https_url)

    @field_validator("target")
    @classmethod
    def _target_not_blank(cls, value: str | tuple[str, ...]) -> str | tuple[str, ...]:
        items = (value,) if isinstance(value, str) else value
        if not items or any(not item.strip() for item in items):
            raise ValueError("target must name at least one non-blank fact id")
        return value

    def to_watch_target(self) -> WatchTarget:
        facts = (self.target,) if isinstance(self.target, str) else tuple(self.target)
        return WatchTarget(
            target_id=self.target_id,
            canonical_url=self.url,
            source_policy_id=self.source_policy_id,
            target_fact_ids=facts,
            page_kind=self.kind,
            check_frequency_days=self.check_frequency_days,
            css_hint=self.css_hint,
            preferred_backend=self.backend,
            manual_only=self.manual_only,
        )


def _watch_policy_issues(
    entry: WatchlistEntry, policy: SourcePolicyRecord, location: str
) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    try:
        canonicalize_url(entry.url)
        SourcePreflight().check_redirect(entry.url, entry.url, policy)
    except (ValueError, UnicodeError) as error:
        issues.append(
            _issue(
                "config_policy_violation",
                f"{location}.url",
                f"url is outside the approved public source domain {policy.domain}: {error}",
            )
        )
    manual_kind = entry.kind is PageKind.MANUAL_CAPTURE
    if entry.kind in _DOCUMENT_KINDS and entry.kind.value not in policy.allowed_page_classes:
        issues.append(
            _issue(
                "config_policy_violation",
                f"{location}.kind",
                f"policy {policy.policy_id!r} does not allow page class {entry.kind.value!r}",
            )
        )
    if entry.backend == "firecrawl":
        issues.append(
            _issue(
                "backend_not_authorized",
                f"{location}.backend",
                "firecrawl is a paid cloud provider and is not authorized; use 'local' or 'manual'",
            )
        )
    manual_entry = entry.backend == "manual" or entry.manual_only
    if manual_kind and not (entry.backend == "manual" and entry.manual_only):
        issues.append(
            _issue(
                "config_policy_violation",
                f"{location}.backend",
                "a manual_capture target must use backend 'manual' with manual_only: true",
            )
        )
    if not manual_entry and (policy.manual_only or not policy.automated_access_permitted):
        issues.append(
            _issue(
                "config_policy_violation",
                f"{location}.backend",
                f"policy {policy.policy_id!r} is manual-only; set backend 'manual' and "
                "manual_only: true",
            )
        )
    return issues


def load_watchlist(
    path: Path,
    *,
    policies: Mapping[str, SourcePolicyRecord],
    aggregator_domains: Iterable[str] = (),
) -> tuple[WatchTarget, ...]:
    """Load ``watchlist.yaml`` into ``WatchTarget`` rows bound to known source policies.

    Entries must point at an issuer page inside a policy's domain, use a page class and access
    mode that policy allows, and never name an aggregator: the watchlist is where a curator
    *promotes* a lead to the issuer URL it pointed at, not a place for the aggregator page.
    """
    entries = _entries(read_structured(path), key="watchlist", path=path)
    issues: list[ConfigIssue] = []
    targets: list[WatchTarget] = []
    seen: set[str] = set()
    extra = tuple(aggregator_domains)
    for index, raw in enumerate(entries):
        location = f"watchlist[{index}]"
        if not isinstance(raw, dict):
            issues.append(_issue("config_invalid_entry", location, "entry must be a mapping"))
            continue
        unknown = _unknown_keys(raw, WatchlistEntry.model_fields, location)
        if unknown:
            issues.extend(unknown)
            continue
        try:
            entry = WatchlistEntry.model_validate(raw)
        except ValidationError as error:
            issues.extend(_validation_issues(error, location))
            continue
        if is_aggregator_host(host_of(entry.url), extra_domains=extra):
            issues.append(
                _issue(
                    "aggregator_domain",
                    f"{location}.url",
                    "a watchlist entry must point at the issuer page, never an aggregator page",
                )
            )
            continue
        policy = policies.get(entry.source_policy_id)
        if policy is None:
            issues.append(
                _issue(
                    "config_policy_missing",
                    f"{location}.source_policy_id",
                    f"no source policy {entry.source_policy_id!r}: record its terms first",
                )
            )
            continue
        problems = _watch_policy_issues(entry, policy, location)
        if problems:
            issues.extend(problems)
            continue
        if entry.target_id in seen:
            issues.append(
                _issue(
                    "config_duplicate_id", f"{location}.target_id", f"duplicate {entry.target_id!r}"
                )
            )
            continue
        seen.add(entry.target_id)
        targets.append(entry.to_watch_target())
    if issues:
        raise ConfigValidationError(path, issues)
    return tuple(targets)
