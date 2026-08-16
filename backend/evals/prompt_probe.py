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
    print("=" * 110)

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

        # Per-node call site analysis
        intake_state = "n/a"
        planner_state = "n/a"
        critic_state = "n/a"
        explainer_state = "n/a"
        failure_reasons: list[str] = []

        if error_detail:
            match = False
            intake_state = "error"
            failure_reasons.append(f"CRASH: {error_detail}")
        elif resp and resp.status == PipelineStatus.NEEDS_CLARIFICATION:
            intake_state = "needs_clarification"
            if exp == "needs_clarification":
                match = True
            else:
                match = False
                failure_reasons.append(f"Intake raised needs_clarification ({resp.unresolved})")
        elif resp and resp.status == PipelineStatus.OK:
            intake_state = "ok"

            caveats = resp.report.caveats if resp.report else []
            caveats_str = " ".join(caveats)

            # Planner node check
            if "Planner fallback used" in caveats_str:
                planner_state = "fallback"
                failure_reasons.append("Planner LLM failed -> deterministic composer fallback")
            elif resp.report and resp.report.itinerary.itinerary_quality == "fallback":
                planner_state = "fallback"
                failure_reasons.append("Itinerary fallback triggered")
            else:
                planner_state = "ok"

            # Critic node check
            critic_state = "ok"

            # Explainer node check
            if "Explainer groundedness gate failed" in caveats_str:
                explainer_state = "ungrounded"
                failure_reasons.append("Explainer failed groundedness -> template fallback")
            elif "Explainer unavailable" in caveats_str:
                explainer_state = "fallback"
                failure_reasons.append("Explainer LLM error/timeout -> template fallback")
            else:
                explainer_state = "ok"

            if exp == "ok":
                # Strict: pass ONLY if no fallback was forced
                if planner_state == "ok" and explainer_state == "ok":
                    match = True
                else:
                    match = False
            else:
                match = False
                failure_reasons.append(f"Expected {exp}, got ok")

        results.append(
            {
                "id": sid,
                "name": sc["name"],
                "expect": exp,
                "actual": actual_status,
                "intake": intake_state,
                "planner": planner_state,
                "critic": critic_state,
                "explainer": explainer_state,
                "match": match,
                "failure_reasons": failure_reasons,
            }
        )

    # Print comprehensive per-call-site table
    print("\n" + "=" * 110)
    print(
        f"{'Scenario ID':<28} {'Expect':<16} {'Intake':<10} {'Planner':<10} "
        f"{'Critic':<8} {'Explainer':<12} {'Overall'}"
    )
    print("-" * 110)
    passed_count = 0
    for r in results:
        res_str = "PASS" if r["match"] else "FAIL"
        if r["match"]:
            passed_count += 1
        print(
            f"{r['id']:<28} {r['expect']:<16} {r['intake']:<10} {r['planner']:<10} "
            f"{r['critic']:<8} {r['explainer']:<12} {res_str}"
        )
        for reason in r["failure_reasons"]:
            print(f"   └─ {reason}")
    print("-" * 110)
    print(f"Summary: {passed_count}/{len(results)} scenarios passed strictly without fallback.")

    live_calls = getattr(client, "calls_recorded", 0) if mode == "record" else 0
    replayed_calls = getattr(client, "calls_replayed", 0) if mode == "replay" else 0
    print(f"Total live LLM calls: {live_calls} (model: {model})")
    print(f"Total replayed LLM calls: {replayed_calls}")
    print("=" * 110 + "\n")

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
