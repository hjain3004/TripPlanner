from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from agents.llm import HostedFreeTier, RecordingLLMClient, ReplayLLMClient
from agents.models import PipelineStatus
from agents.pipeline import run_pipeline
from core.db import load_kb


def run_prompt_probe(
    scenarios_file: Path,
    recordings_dir: Path,
    mode: str = "replay",
    model: str = "llama-3.1-8b-instant",
    scenario_id_filter: str | None = None,
) -> dict[str, Any]:
    kb = load_kb()
    data = yaml.safe_load(scenarios_file.read_text(encoding="utf-8"))
    scenarios = data.get("scenarios", [])
    if scenario_id_filter:
        scenarios = [s for s in scenarios if s["id"] == scenario_id_filter]

    # Setup client
    if mode == "record":
        os.environ["TRIPWISE_LLM_MODEL"] = model
        os.environ["TRIPWISE_LLM_MAX_CALLS"] = "500"
        hosted = HostedFreeTier()
        client: Any = RecordingLLMClient(hosted, recordings_dir=recordings_dir)
    else:
        client = ReplayLLMClient(recordings_dir=recordings_dir, model=model)

    results: list[dict[str, Any]] = []

    print(f"\nRunning Prompt Probe ({mode.upper()} mode, model: {model}, {len(scenarios)} tests)")
    print("=" * 90)

    for sc in scenarios:
        sid = sc["id"]
        req = sc["request"]
        exp = sc["expect"]
        print(f"-> Running [{sid}]: {sc['name']}...")

        error_detail: str | None = None
        resp = None
        try:
            resp = run_pipeline(
                raw_request=req,
                kb=kb,
                llm=client,
                booking_date=date(2026, 8, 1),
            )
        except Exception as exc:
            error_detail = f"Exception: {type(exc).__name__}: {exc}"

        actual_status = resp.status.value if resp else "error"
        match = False

        if error_detail:
            match = False
            status_desc = f"CRASH: {error_detail}"
        elif exp == "ok":
            if resp and resp.status == PipelineStatus.OK:
                match = True
                if resp.report and resp.report.itinerary.itinerary_quality == "fallback":
                    status_desc = "OK (itinerary fallback)"
                else:
                    status_desc = "OK"
            else:
                match = False
                unresolved = resp.unresolved if resp else []
                status_desc = f"Mismatch: expected OK, got {actual_status} (unres={unresolved})"
        elif exp == "needs_clarification":
            if resp and resp.status == PipelineStatus.NEEDS_CLARIFICATION:
                match = True
                status_desc = f"Needs Clarification ({resp.unresolved})"
            else:
                match = False
                status_desc = f"Mismatch: expected needs_clarification, got {actual_status}"
        elif exp == "capability_absent":
            if (
                resp
                and resp.report
                and resp.report.region_capability
                and resp.report.region_capability.catalog_status == "absent"
            ):
                match = True
                status_desc = "OK (capability absent)"
            else:
                match = False
                status_desc = f"Mismatch: expected capability absent, got {actual_status}"
        else:
            match = actual_status == exp
            status_desc = actual_status

        results.append(
            {
                "id": sid,
                "name": sc["name"],
                "expect": exp,
                "actual": actual_status,
                "match": match,
                "desc": status_desc,
            }
        )

    # Print summary table
    print("\n" + "=" * 90)
    print(f"{'Scenario ID':<30} {'Expect':<20} {'Actual':<20} {'Result'}")
    print("-" * 90)
    passed_count = 0
    for r in results:
        res_str = "PASS" if r["match"] else "FAIL"
        if r["match"]:
            passed_count += 1
        print(f"{r['id']:<30} {r['expect']:<20} {r['actual']:<20} {res_str}")
        if not r["match"]:
            print(f"   └─ {r['desc']}")
    print("-" * 90)
    print(f"Summary: {passed_count}/{len(results)} scenarios passed expectation.")

    live_calls = getattr(client, "calls_recorded", 0) if mode == "record" else 0
    replayed_calls = getattr(client, "calls_replayed", 0) if mode == "replay" else 0
    print(f"Total live LLM calls: {live_calls} (model: {model})")
    print(f"Total replayed LLM calls: {replayed_calls}")
    print("=" * 90 + "\n")

    return {
        "passed": passed_count,
        "total": len(results),
        "live_calls": live_calls,
        "replayed_calls": replayed_calls,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prompt probe runner for scenario evaluations.")
    parser.add_argument("--record", action="store_true", help="Run live and record responses")
    parser.add_argument("--replay", action="store_true", help="Replay from cache without network")
    parser.add_argument("--model", default="llama-3.1-8b-instant", help="LLM model name")
    parser.add_argument("--scenario", default=None, help="Filter by scenario ID")
    parser.add_argument(
        "--scenarios-file",
        type=Path,
        default=Path(__file__).parent / "scenarios.yaml",
        help="Path to scenarios YAML",
    )
    parser.add_argument(
        "--recordings-dir",
        type=Path,
        default=Path(__file__).parent / "recorded",
        help="Directory for recording JSON fixtures",
    )

    args = parser.parse_args()
    mode = "record" if args.record else "replay"

    run_prompt_probe(
        scenarios_file=args.scenarios_file,
        recordings_dir=args.recordings_dir,
        mode=mode,
        model=args.model,
        scenario_id_filter=args.scenario,
    )


if __name__ == "__main__":
    main()
