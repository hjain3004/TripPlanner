"""Card-bank configuration loaders (spec 05 sections 0-1): refusals and promotion rules.

Every file here is synthetic. The point under test is that a bad configuration is refused with
typed, located issues *before* anything is fetched or stored, and that an aggregator can be a
lead source but never a source of facts.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from ingestion.config_loaders import (
    AGGREGATOR_DOMAINS,
    ConfigValidationError,
    DiscoverySource,
    is_aggregator_host,
    load_discovery_sources,
    load_source_policies,
    load_watchlist,
)
from ingestion.contracts import DiscoveryCandidate, PageKind

TODAY = date(2026, 11, 4)


def write(path: Path, data: Any) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def policy(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "policy_id": "synth-issuer",
        "name": "SYNTHETIC issuer",
        "owner": "fixture",
        "domain": "example.invalid",
        "source_url": "https://www.example.invalid/card",
        "terms_url": "https://www.example.invalid/terms",
        "terms_read_on": "2026-11-01",
        "automated_access_permitted": False,
        "manual_only": True,
        "allowed_page_classes": ["card_page", "tnc_pdf"],
        "reviewed_on": "2026-11-01",
        "reviewed_by": "alice",
    }
    return {**base, **over}


def lead_source(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "SyntheticExpert",
        "url": "https://www.cardexpert.in/",
        "corridor": "IN",
        "tos_url": "https://www.cardexpert.in/terms-of-use/",
        "tos_read_on": "2026-11-01",
        "automated_access_permitted": False,
        "manual_only": True,
    }
    return {**base, **over}


def watch(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "target_id": "t1",
        "url": "https://www.example.invalid/card",
        "kind": "card_page",
        "target": ["hdfc-infinia"],
        "source_policy_id": "synth-issuer",
        "check_frequency_days": 365,
        "backend": "manual",
        "manual_only": True,
    }
    return {**base, **over}


def codes(error: ConfigValidationError) -> set[str]:
    return {issue.code for issue in error.issues}


# ------------------------------------------------------------------ source policies


def test_a_valid_policy_file_loads_as_the_existing_contract(tmp_path: Path) -> None:
    loaded = load_source_policies(write(tmp_path / "p.yaml", [policy()]))
    assert [p.policy_id for p in loaded] == ["synth-issuer"]
    assert loaded[0].manual_only is True


def test_a_policy_file_may_hold_one_mapping_or_a_keyed_list(tmp_path: Path) -> None:
    assert load_source_policies(write(tmp_path / "a.yaml", policy()))[0].policy_id
    keyed = write(tmp_path / "b.yaml", {"source_policies": [policy()]})
    assert load_source_policies(keyed)[0].policy_id


@pytest.mark.parametrize("domain", sorted(AGGREGATOR_DOMAINS))
def test_no_aggregator_can_be_a_source_policy(tmp_path: Path, domain: str) -> None:
    with pytest.raises(ConfigValidationError) as refused:
        load_source_policies(write(tmp_path / "p.yaml", [policy(domain=domain)]))
    assert "aggregator_domain" in codes(refused.value)


def test_a_configured_discovery_domain_is_also_refused_as_a_source(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError) as refused:
        load_source_policies(
            write(tmp_path / "p.yaml", [policy(domain="newlead.example")]),
            aggregator_domains=["newlead.example"],
        )
    assert "aggregator_domain" in codes(refused.value)


def test_subdomains_of_an_aggregator_match_but_lookalikes_do_not() -> None:
    assert is_aggregator_host("www.cardexpert.in")
    assert not is_aggregator_host("notcardexpert.in")


def test_every_problem_in_a_policy_file_is_reported_together(tmp_path: Path) -> None:
    bad = [
        policy(policy_id="a", unexpected="x"),
        policy(policy_id="b", domain="https://www.hdfc.bank.in/path"),
        policy(policy_id="c", source_url="https://elsewhere.test/x"),
        policy(policy_id="d", automated_access_permitted=False, manual_only=False),
        policy(policy_id="dup"),
        policy(policy_id="dup"),
    ]
    with pytest.raises(ConfigValidationError) as refused:
        load_source_policies(write(tmp_path / "p.yaml", bad))
    found = {(i.code, i.location.split(".")[0]) for i in refused.value.issues}
    assert ("config_unknown_key", "source_policies[0]") in found
    assert ("config_invalid_entry", "source_policies[1]") in found
    assert ("config_policy_violation", "source_policies[2]") in found
    assert ("config_invalid_entry", "source_policies[3]") in found
    assert ("config_duplicate_id", "source_policies[5]") in found


@pytest.mark.parametrize(
    ("name", "content", "code"),
    [
        ("missing.yaml", None, "config_unreadable"),
        ("bad.yaml", "key: [unclosed", "config_invalid_syntax"),
        ("bad.json", "{not json", "config_invalid_syntax"),
        ("data.txt", "x", "config_unsupported_format"),
        ("empty.yaml", "[]", "config_invalid_shape"),
        ("scalar.yaml", "just text", "config_invalid_shape"),
    ],
)
def test_unreadable_or_malformed_files_are_typed_refusals(
    tmp_path: Path, name: str, content: str | None, code: str
) -> None:
    path = tmp_path / name
    if content is not None:
        path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigValidationError) as refused:
        load_source_policies(path)
    assert code in codes(refused.value)


def test_an_oversized_file_is_refused_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / "big.yaml"
    path.write_text("# " + "x" * 1_100_000, encoding="utf-8")
    with pytest.raises(ConfigValidationError) as refused:
        load_source_policies(path)
    assert "config_too_large" in codes(refused.value)


# ------------------------------------------------------------------ discovery sources


def test_discovery_sources_carry_a_terms_record_and_never_a_fact(tmp_path: Path) -> None:
    sources = load_discovery_sources(write(tmp_path / "d.yaml", [lead_source()]), today=TODAY)
    assert sources[0].domain == "www.cardexpert.in" and sources[0].manual_only
    # structurally: no provenance, and no field that could hold a financial value
    assert "provenance" not in DiscoverySource.model_fields
    assert not {"annual_fee_minor", "claim_summary", "provenance"} & set(
        DiscoverySource.model_fields
    )


@pytest.mark.parametrize(
    "over",
    [
        {"automated_access_permitted": True, "manual_only": True},  # contradictory
        {
            "automated_access_permitted": False,
            "manual_only": False,
        },  # forbids automation yet not manual
    ],
)
def test_the_access_mode_must_be_exactly_one(tmp_path: Path, over: dict[str, Any]) -> None:
    with pytest.raises(ConfigValidationError):
        load_discovery_sources(write(tmp_path / "d.yaml", [lead_source(**over)]), today=TODAY)


def test_no_discovery_source_without_its_terms_record(tmp_path: Path) -> None:
    entry = lead_source()
    del entry["tos_url"]
    del entry["tos_read_on"]
    with pytest.raises(ConfigValidationError) as refused:
        load_discovery_sources(write(tmp_path / "d.yaml", [entry]), today=TODAY)
    assert {i.location for i in refused.value.issues} >= {
        "discovery_sources[0].tos_url",
        "discovery_sources[0].tos_read_on",
    }


def test_a_lead_source_cannot_smuggle_a_financial_value(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError) as refused:
        load_discovery_sources(
            write(tmp_path / "d.yaml", [lead_source(annual_fee_minor=1250000)]), today=TODAY
        )
    assert "config_unknown_key" in codes(refused.value)


def test_terms_cannot_have_been_read_in_the_future(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError):
        load_discovery_sources(
            write(tmp_path / "d.yaml", [lead_source(tos_read_on="2027-01-01")]), today=TODAY
        )


def test_a_discovery_candidate_still_has_no_provenance() -> None:
    # The pre-existing structural invariant the loaders are built around (spec 05 section 0).
    assert "provenance" not in DiscoveryCandidate.model_fields


# ------------------------------------------------------------------ watchlist


def load(tmp_path: Path, entries: list[dict[str, Any]], **policies: Any) -> Any:
    loaded = load_source_policies(write(tmp_path / "p.yaml", [policy(**policies)]))
    by_id = {p.policy_id: p for p in loaded}
    return load_watchlist(write(tmp_path / "w.yaml", entries), policies=by_id)


def test_a_watchlist_entry_becomes_a_watch_target(tmp_path: Path) -> None:
    (target,) = load(tmp_path, [watch(kind="manual_capture", target="hdfc-infinia")])
    assert target.page_kind is PageKind.MANUAL_CAPTURE
    assert target.target_fact_ids == ("hdfc-infinia",)
    assert target.preferred_backend == "manual" and target.manual_only


def test_a_watch_entry_needs_a_known_policy(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError) as refused:
        load(tmp_path, [watch(source_policy_id="nope")])
    assert "config_policy_missing" in codes(refused.value)


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"url": "https://www.cardexpert.in/some-card"}, "aggregator_domain"),
        ({"url": "https://elsewhere.test/card"}, "config_policy_violation"),
        ({"kind": "offer_page"}, "config_policy_violation"),  # class not allowed by the policy
        ({"backend": "firecrawl", "manual_only": False}, "backend_not_authorized"),
        (
            {"backend": "local", "manual_only": False},
            "config_policy_violation",
        ),  # manual-only policy
        (
            {"kind": "manual_capture", "backend": "local", "manual_only": False},
            "config_policy_violation",
        ),
        ({"unknown": 1}, "config_unknown_key"),
        ({"check_frequency_days": 0}, "config_invalid_entry"),
        ({"target": []}, "config_invalid_entry"),
    ],
)
def test_a_watch_entry_the_policy_does_not_allow_is_refused(
    tmp_path: Path, over: dict[str, Any], code: str
) -> None:
    with pytest.raises(ConfigValidationError) as refused:
        load(tmp_path, [watch(**over)])
    assert code in codes(refused.value)


def test_an_automated_watch_entry_needs_a_policy_that_permits_automation(tmp_path: Path) -> None:
    allowed = load(
        tmp_path,
        [watch(backend="local", manual_only=False)],
        automated_access_permitted=True,
        manual_only=False,
    )
    assert allowed[0].preferred_backend == "local"


def test_firecrawl_watch_entry_requires_explicit_eligibility_and_automated_html_policy(
    tmp_path: Path,
) -> None:
    automated_policies = {
        p.policy_id: p
        for p in load_source_policies(
            write(tmp_path / "p.yaml", [policy(automated_access_permitted=True, manual_only=False)])
        )
    }
    manual_policies = {
        p.policy_id: p for p in load_source_policies(write(tmp_path / "pm.yaml", [policy()]))
    }
    w_html = write(tmp_path / "w_html.yaml", [watch(backend="firecrawl", manual_only=False)])
    allowed = load_watchlist(w_html, policies=automated_policies, allow_firecrawl=True)
    assert allowed[0].preferred_backend == "firecrawl"
    assert allowed[0].manual_only is False

    with pytest.raises(ConfigValidationError) as manual_refused:
        load_watchlist(w_html, policies=manual_policies, allow_firecrawl=True)
    assert "config_policy_violation" in codes(manual_refused.value)

    w_pdf = write(
        tmp_path / "w_pdf.yaml",
        [watch(backend="firecrawl", manual_only=False, kind="tnc_pdf")],
    )
    with pytest.raises(ConfigValidationError) as pdf_refused:
        load_watchlist(w_pdf, policies=automated_policies, allow_firecrawl=True)
    assert "backend_not_authorized" in codes(pdf_refused.value)


def test_duplicate_target_ids_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError) as refused:
        load(tmp_path, [watch(), watch()])
    assert "config_duplicate_id" in codes(refused.value)


@pytest.mark.parametrize(
    "domain", ["bankbazaar.com.", "www.bankbazaar.com.", "BANKBAZAAR.COM", "\uff42ankbazaar.com"]
)
def test_an_aggregator_policy_is_refused_however_its_domain_is_spelled(
    tmp_path: Path, domain: str
) -> None:
    with pytest.raises(ConfigValidationError) as refused:
        load_source_policies(write(tmp_path / "p.yaml", [policy(domain=domain)]))
    assert "aggregator_domain" in codes(refused.value)


def test_an_aggregator_watch_url_is_refused_however_its_host_is_spelled(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError) as refused:
        load(tmp_path, [watch(url="https://www.bankbazaar.com./c")])
    assert "aggregator_domain" in codes(refused.value)


def test_a_yaml_alias_bomb_is_refused_before_it_can_exhaust_memory(tmp_path: Path) -> None:
    """A few hundred bytes of aliases expand to gigabytes when the document is validated."""
    rows = ["a: &a [x,x,x,x,x,x,x,x,x]"]
    previous = "a"
    for name in "bcdefghi":
        rows.append(f"{name}: &{name} [{','.join('*' + previous for _ in range(9))}]")
        previous = name
    bomb = tmp_path / "bomb.yaml"
    bomb.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ConfigValidationError) as refused:
        load_source_policies(bomb)
    assert codes(refused.value) == {"config_invalid_syntax"}
    assert "aliases are not allowed" in refused.value.issues[0].message


def test_plain_yaml_with_anchors_free_content_still_loads(tmp_path: Path) -> None:
    assert load_source_policies(write(tmp_path / "p.yaml", [policy()]))[0].policy_id
