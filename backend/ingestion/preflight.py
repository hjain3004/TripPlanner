"""Deterministic source, URL, redirect, and robots preflight."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from ingestion.contracts import FetchFailureKind, FetchRequest, SourcePolicyRecord

_TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_USER_AGENT = "Tripwise-FinancialIngestion/1.0"


def canonicalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must use http or https and include a host")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("URL cannot contain credentials or a fragment")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    port = parsed.port
    if port is not None and (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        port = None
    netloc = host if port is None else f"{host}:{port}"
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMETERS and not key.lower().startswith("utm_")
    ]
    query.sort()
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, urlencode(query), ""))


def _public_host(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def _domain_matches(host: str, domain: str) -> bool:
    normalized = domain.strip().lower().lstrip(".")
    return host == normalized or host.endswith(f".{normalized}")


@dataclass(frozen=True)
class RobotsGroup:
    agents: tuple[str, ...]
    rules: tuple[tuple[bool, str], ...]
    crawl_delay_seconds: float | None = None


class RobotsRules:
    """A small, offline robots parser; no network access is performed."""

    def __init__(self, groups: tuple[RobotsGroup, ...]) -> None:
        self.groups = groups

    @classmethod
    def parse(cls, text: str) -> RobotsRules:
        groups: list[RobotsGroup] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        delay: float | None = None

        def flush() -> None:
            nonlocal agents, rules, delay
            if agents:
                groups.append(RobotsGroup(tuple(agents), tuple(rules), delay))
            agents, rules, delay = [], [], None

        for raw_line in text.splitlines() + [""]:
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                flush()
                continue
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            lowered = key.lower()
            if lowered == "user-agent":
                if rules or delay is not None:
                    flush()
                agents.append(value.lower())
            elif lowered == "disallow" and agents:
                rules.append((False, value))
            elif lowered == "allow" and agents:
                rules.append((True, value))
            elif lowered == "crawl-delay" and agents:
                try:
                    delay = float(value)
                except ValueError:
                    delay = None
        return cls(tuple(groups))

    def _group(self, user_agent: str) -> RobotsGroup | None:
        lowered = user_agent.lower()
        matches = [
            (len(agent), group)
            for group in self.groups
            for agent in group.agents
            if agent == "*" or agent in lowered
        ]
        return max(matches, key=lambda item: item[0])[1] if matches else None

    def allowed(self, url: str, *, user_agent: str = _USER_AGENT) -> bool:
        group = self._group(user_agent)
        if group is None:
            return True
        path = urlsplit(url).path or "/"
        matching = [
            (len(rule), allow) for allow, rule in group.rules if rule and path.startswith(rule)
        ]
        if not matching:
            return True
        return max(matching, key=lambda item: item[0])[1]

    def crawl_delay(self, *, user_agent: str = _USER_AGENT) -> float | None:
        group = self._group(user_agent)
        return None if group is None else group.crawl_delay_seconds


@dataclass(frozen=True)
class PreflightDecision:
    allowed: bool
    canonical_url: str
    failure_kind: FetchFailureKind | None = None
    diagnostic: str | None = None


class SourcePreflight:
    def __init__(self, *, user_agent: str = _USER_AGENT) -> None:
        self.user_agent = user_agent

    def check(
        self,
        request: FetchRequest,
        policy: SourcePolicyRecord,
        *,
        robots: RobotsRules | None = None,
        page_class: str | None = None,
        manual: bool = False,
    ) -> PreflightDecision:
        try:
            url = canonicalize_url(request.canonical_url)
            host = urlsplit(url).hostname or ""
        except (ValueError, UnicodeError) as error:
            return PreflightDecision(
                False, request.canonical_url, FetchFailureKind.POLICY_BLOCKED, str(error)
            )
        if not _public_host(host):
            return PreflightDecision(
                False, url, FetchFailureKind.POLICY_BLOCKED, "private or special-use host"
            )
        if not _domain_matches(host, policy.domain):
            return PreflightDecision(
                False, url, FetchFailureKind.POLICY_BLOCKED, "host is outside source policy"
            )
        if page_class is not None and page_class not in policy.allowed_page_classes:
            return PreflightDecision(
                False, url, FetchFailureKind.POLICY_BLOCKED, "page class is not allowed"
            )
        if not manual and (policy.manual_only or not policy.automated_access_permitted):
            return PreflightDecision(
                False, url, FetchFailureKind.POLICY_BLOCKED, "source is manual-only"
            )
        if (
            not manual
            and robots is not None
            and not robots.allowed(url, user_agent=self.user_agent)
        ):
            return PreflightDecision(
                False, url, FetchFailureKind.ROBOTS_BLOCKED, "robots.txt disallows the path"
            )
        return PreflightDecision(True, url)

    def check_redirect(self, original_url: str, final_url: str, policy: SourcePolicyRecord) -> str:
        original = canonicalize_url(original_url)
        final = canonicalize_url(final_url)
        host = urlsplit(final).hostname or ""
        if not _public_host(host) or not _domain_matches(host, policy.domain):
            raise ValueError("redirect leaves the approved public source domain")
        if urlsplit(original).scheme != urlsplit(final).scheme:
            raise ValueError("redirect changes URL scheme")
        return final


def robots_url(url: str) -> str:
    return urljoin(url, "/robots.txt")
