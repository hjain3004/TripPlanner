"""Real-process restart behavior of durable planning jobs.

Spawns actual server processes, kills them with SIGKILL mid-plan, freezes one with SIGSTOP and
restarts others over the same on-disk SQLite files (``evals/durable_jobs_demo.py``). Exception
injection and in-process restarts are covered in ``test_durable_jobs.py``; this proves the same
properties across genuine process death. Offline: loopback only, scripted model.
"""

from __future__ import annotations

from pathlib import Path

from evals.durable_jobs_demo import run


def test_planning_jobs_survive_real_process_kills_without_redispatch(tmp_path: Path) -> None:
    transcript: list[str] = []
    facts = run(tmp_path, say=transcript.append)

    failed = [name for name, held in facts.items() if not held]
    assert not failed, "\n".join(transcript)
    assert len(facts) >= 20  # the demonstration actually ran its scenarios
