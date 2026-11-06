"""Real-process demonstration of restart-safe planning jobs.

Starts actual ``uvicorn`` server processes over a shared on-disk data directory, with a scripted
offline model (every call is appended to ``llm-calls.log``, so "nothing was redispatched" is
counted, not assumed). It then kills them with ``SIGKILL`` mid-plan, freezes one with
``SIGSTOP``, restarts others over the same SQLite files, and checks what survived::

    python -m evals.durable_jobs_demo run --data-dir /path/to/empty/dir

Exit status 0 means every check held. ``serve`` is the server entry point the demo spawns.
No network beyond loopback, no credentials, no live model or provider.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTED_RUNS = 8


# --------------------------------------------------------------------------------------- #
# The server process
# --------------------------------------------------------------------------------------- #


def serve(data_dir: Path, port: int, *, hold: bool) -> None:
    """Run the real API on loopback with a scripted model. ``hold`` blocks each intake call
    until ``<data_dir>/release`` exists, which keeps a job reliably in flight."""
    os.environ["TRIPWISE_DATA_DIR"] = str(data_dir)
    import uvicorn

    import api.main as api_main
    from agents.llm import ScriptedLLMClient
    from agents.models import CriticVerdict, ExplainerOutput
    from core.models import UserWallet
    from evals import a4_support

    log = data_dir / "llm-calls.log"

    class DemoLLM(ScriptedLLMClient):
        def complete_json(self, *, node: str, **kwargs: Any) -> Any:
            with log.open("a", encoding="utf-8") as handle:
                handle.write(f"{os.getpid()} {node}\n")
            if hold and node == "intake":
                (data_dir / "held").write_text(str(os.getpid()))
                deadline = time.monotonic() + 120
                while not (data_dir / "release").exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
            return super().complete_json(node=node, **kwargs)

    llm = DemoLLM({})
    scripts = llm._scripts
    for n in range(SCRIPTED_RUNS):
        scripts.setdefault("intake", []).append(a4_support._spec(UserWallet(card_ids=[])))
        scripts.setdefault("planner", []).append(a4_support._itinerary())
        scripts.setdefault("critic", []).append(CriticVerdict(passed=True))
        scripts.setdefault("explainer", []).append(
            ExplainerOutput(
                summary=f"Scripted plan {n + 1}.",
                itinerary_overview="Grounded itinerary.",
                payment_overview="Grounded payments.",
            )
        )
    # Call-time lookups: the job starters import these names from api.main when they run.
    api_main.get_llm = lambda: llm  # type: ignore[assignment]
    api_main.get_booking_date = lambda: date(2026, 10, 24)  # type: ignore[assignment]
    api_main.get_trace_dir = lambda: data_dir / "traces"  # type: ignore[assignment]
    uvicorn.run(api_main.app, host="127.0.0.1", port=port, log_level="warning")


# --------------------------------------------------------------------------------------- #
# The orchestrating side
# --------------------------------------------------------------------------------------- #


class Api:
    """A tiny HTTP client that keeps cookies by hand (they are ``Secure``; the demo is plain
    loopback HTTP), shaped like the test client the interview helpers expect."""

    def __init__(self, base_url: str) -> None:
        import httpx

        self.http = httpx.Client(base_url=base_url, timeout=60)
        self.cookies: dict[str, str] = {}

    def _call(self, method: str, url: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", None) or {})
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        response = self.http.request(method, url, headers=headers, **kwargs)
        for raw in response.headers.get_list("set-cookie"):
            name, _, rest = raw.partition("=")
            self.cookies[name.strip()] = rest.split(";", 1)[0]
        return response

    def get(self, url: str, **kwargs: Any) -> Any:
        return self._call("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._call("POST", url, **kwargs)

    def sign_up(self, email: str) -> None:
        from evals.a4_support import PASSWORD

        body = {"email": email, "password": PASSWORD}
        assert self.post("/auth/register", json=body).status_code in {200, 201}
        assert self.post("/auth/login", json=body).status_code == 200


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Server:
    def __init__(self, data_dir: Path, *, hold: bool = False) -> None:
        self.data_dir = data_dir
        self.port = _free_port()
        env = {**os.environ, "TRIPWISE_DATA_DIR": str(data_dir)}
        command = [
            sys.executable,
            "-m",
            "evals.durable_jobs_demo",
            "serve",
            "--data-dir",
            str(data_dir),
            "--port",
            str(self.port),
            *(["--hold"] if hold else []),
        ]
        self.log = (data_dir / f"server-{self.port}.log").open("w")
        self.proc = subprocess.Popen(  # noqa: S603
            command, cwd=BACKEND, env=env, stdout=self.log, stderr=subprocess.STDOUT
        )
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._wait_ready()

    def _wait_ready(self) -> None:
        import httpx

        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited early: see {self.log.name}")
            with contextlib.suppress(httpx.HTTPError):
                if httpx.get(f"{self.base_url}/health", timeout=2).status_code == 200:
                    return
            time.sleep(0.2)
        raise RuntimeError("server did not become ready")

    def client(self) -> Api:
        return Api(self.base_url)

    def kill(self) -> None:
        """A real, unclean process death: no shutdown hooks, no thread joins."""
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGKILL)
        self.proc.wait(timeout=30)
        self.log.close()


def llm_calls(data_dir: Path) -> Counter[str]:
    log = data_dir / "llm-calls.log"
    if not log.exists():
        return Counter()
    return Counter(line.split()[1] for line in log.read_text().splitlines() if line.strip())


def _wait(condition: Callable[[], bool], what: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def run(data_dir: Path, *, say: Callable[[str], None] = print) -> dict[str, bool]:
    """Run every scenario against ``data_dir``; returns ``{check name: held}``."""
    data_dir.mkdir(parents=True, exist_ok=True)
    seeded = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "core.db", "seed"],
        cwd=BACKEND,
        env={**os.environ, "TRIPWISE_DATA_DIR": str(data_dir)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert seeded.returncode == 0, seeded.stderr

    from accounts.store import AccountStore
    from evals.a4_support import confirm, csrf, run_interview, wait_for_job

    facts: dict[str, bool] = {}

    def check(name: str, held: bool, detail: str = "") -> None:
        facts[name] = bool(held)
        say(f"  [{'ok' if held else 'FAILED'}] {name}" + (f"  ({detail})" if detail else ""))

    servers: list[Server] = []

    def start(*, hold: bool = False) -> Server:
        server = Server(data_dir, hold=hold)
        servers.append(server)
        return server

    def calls_total() -> int:
        return sum(llm_calls(data_dir).values())

    try:
        # ---- 1. a completed plan survives SIGKILL --------------------------------------- #
        say("1. complete a plan, SIGKILL the server, restart, read the same report")
        a = start()
        user1 = a.client()
        user1.sign_up("traveler@example.com")
        session1 = confirm(user1, run_interview(user1))
        done1 = wait_for_job(user1, session1["id"])
        check("plan completes before the kill", done1["status"] == "complete")
        calls_after_plan1 = calls_total()
        a.kill()
        b = start(hold=True)
        again = b.client()
        again.cookies = dict(user1.cookies)  # same browser session: cookies are not server state
        reopened = again.get(f"/planning/sessions/{session1['id']}/job")
        check(
            "report is byte-identical after a SIGKILL restart",
            reopened.status_code == 200 and reopened.json() == done1,
        )
        legacy = again.get(f"/plan/{session1['job_id']}")
        check("GET /plan/{job_id} returns the same report", legacy.json() == done1)
        check("reopening called no model", calls_total() == calls_after_plan1)

        # ---- 2. interrupted mid-flight ---------------------------------------------------- #
        say("2. SIGKILL the server while a plan is inside a model call")
        (data_dir / "release").unlink(missing_ok=True)
        (data_dir / "held").unlink(missing_ok=True)
        session2 = confirm(again, run_interview(again), event="confirm-2")
        _wait(lambda: (data_dir / "held").exists(), "the plan to reach its first model call")
        running = again.get(f"/planning/sessions/{session2['id']}/job").json()
        check("job reads running while its worker lives", running["status"] == "running")
        calls_in_flight = calls_total()
        b.kill()
        c = start()
        after = c.client()
        after.cookies = dict(user1.cookies)
        replay = after.post(
            f"/planning/sessions/{session2['id']}/confirm",
            headers=csrf(after),
            json={
                "expected_version": session2["version"],
                "brief": after.get(f"/planning/sessions/{session2['id']}").json()["brief"],
                "client_event_id": "confirm-2",
            },
        )
        check(
            "replaying the confirmation starts no new job",
            replay.status_code == 202 and replay.json()["job_id"] == session2["job_id"],
        )
        interrupted = after.get(f"/planning/sessions/{session2['id']}/job").json()
        polled_again = after.get(f"/plan/{session2['job_id']}").json()
        error = interrupted.get("error") or {}
        check(
            "restart reports the job as interrupted, not running",
            interrupted["status"] == "failed" and error.get("code") == "JOB_INTERRUPTED",
            error.get("message", "")[:90],
        )
        check("interrupted job has no report", interrupted["report"] is None)
        check("polling again says the same thing", polled_again.get("error") == error)
        check(
            "no model call was dispatched by restart, replay or polling",
            calls_total() == calls_in_flight,
        )

        # ---- 3. explicit retry ----------------------------------------------------------- #
        say("3. retry through the normal confirmation")
        current = after.get(f"/planning/sessions/{session2['id']}").json()
        retry = after.post(
            f"/planning/sessions/{session2['id']}/confirm",
            headers=csrf(after),
            json={
                "expected_version": current["version"],
                "brief": current["brief"],
                "client_event_id": "confirm-2-retry",
            },
        )
        check(
            "retry is a new job",
            retry.status_code == 202 and retry.json()["job_id"] != session2["job_id"],
        )
        done2 = wait_for_job(after, session2["id"])
        check("the retry completes", done2["status"] == "complete")

        # ---- 4. save and re-run, then restart ---------------------------------------------- #
        say("4. save the pre-restart plan, re-run it, SIGKILL, read the durable result")
        saved = after.post(
            "/account/trips",
            headers=csrf(after),
            json={"session_id": session1["id"], "client_event_id": "save-1"},
        )
        check("a plan finished before two restarts can be saved", saved.status_code == 201)
        trip_id = saved.json()["trip"]["id"]
        rerun = after.post(
            f"/account/trips/{trip_id}/reruns",
            headers=csrf(after),
            json={"client_event_id": "rr-1"},
        )
        rerun_job = rerun.json()["job_id"]

        def rerun_state(api: Api) -> dict[str, Any]:
            return dict(api.get(f"/account/trips/{trip_id}/reruns/{rerun_job}").json())

        _wait(lambda: rerun_state(after)["status"] not in {"queued", "running"}, "the re-run")
        check("re-run completes as revision 2", rerun_state(after).get("revision") == 2)
        calls_after_rerun = calls_total()
        c.kill()
        d = start()
        later = d.client()
        later.cookies = dict(user1.cookies)
        state = rerun_state(later)
        check(
            "re-run status survives the kill",
            state["status"] == "complete" and state["revision"] == 2,
        )
        replay_rerun = later.post(
            f"/account/trips/{trip_id}/reruns",
            headers=csrf(later),
            json={"client_event_id": "rr-1"},
        )
        check(
            "replaying the re-run start returns the same job",
            replay_rerun.status_code == 202 and replay_rerun.json()["job_id"] == rerun_job,
        )
        revisions = later.get(f"/account/trips/{trip_id}").json()
        check(
            "the trip holds exactly revision 1 and the re-run's revision 2",
            [r["revision"] for r in revisions["revisions"]] == [1, 2],
        )
        check("none of that called a model", calls_total() == calls_after_rerun)

        # ---- 5. a stale completion from a frozen process --------------------------------- #
        say(
            "5. freeze a server mid-plan, start another, thaw the first: its late result is refused"
        )
        (data_dir / "held").unlink(missing_ok=True)
        (data_dir / "release").unlink(missing_ok=True)
        e = start(hold=True)
        victim = e.client()
        victim.cookies = dict(user1.cookies)
        session3 = confirm(victim, run_interview(victim), event="confirm-3")
        _wait(lambda: (data_dir / "held").exists(), "the frozen plan's first model call")
        os.kill(e.proc.pid, signal.SIGSTOP)
        f = start()
        observer = f.client()
        observer.cookies = dict(user1.cookies)
        seen = observer.get(f"/plan/{session3['job_id']}").json()
        check(
            "a second process reports the frozen job interrupted",
            seen["status"] == "failed"
            and (seen.get("error") or {}).get("code") == "JOB_INTERRUPTED",
        )
        explainer_before = llm_calls(data_dir)["explainer"]
        (data_dir / "release").write_text("go")
        os.kill(e.proc.pid, signal.SIGCONT)
        _wait(
            lambda: llm_calls(data_dir)["explainer"] > explainer_before, "the thawed plan to finish"
        )
        time.sleep(1.0)
        after_thaw = observer.get(f"/plan/{session3['job_id']}").json()
        check(
            "the thawed process could not publish a report",
            after_thaw["status"] == "failed" and after_thaw["report"] is None,
        )

        # ---- 6. wrong owner == missing ------------------------------------------------------ #
        say("6. another account sees the job exactly as it sees a missing one")
        stranger = f.client()
        stranger.sign_up("stranger@example.com")
        real = stranger.get(f"/plan/{session1['job_id']}")
        missing = stranger.get("/plan/" + "0" * 32)
        check(
            "wrong-owner response equals missing-job response",
            real.status_code == missing.status_code == 404 and real.json() == missing.json(),
        )

        # ---- 7. deleting the owner while work is pending ---------------------------------- #
        say("7. delete the account while a plan is in flight; its completion recreates nothing")
        (data_dir / "held").unlink(missing_ok=True)
        (data_dir / "release").unlink(missing_ok=True)
        e.kill()
        g = start(hold=True)
        leaver = g.client()
        leaver.sign_up("leaver@example.com")
        leaver_id = str(leaver.get("/auth/me").json()["id"])
        session4 = confirm(leaver, run_interview(leaver), event="confirm-4")
        _wait(lambda: (data_dir / "held").exists(), "the pending plan's first model call")
        store = AccountStore.open(data_dir / "accounts.sqlite")
        check("the pending job is recorded", len(store.planning_jobs(leaver_id)) == 1)
        explainer_before = llm_calls(data_dir)["explainer"]
        store.delete_user(leaver_id)
        (data_dir / "release").write_text("go")
        _wait(
            lambda: llm_calls(data_dir)["explainer"] > explainer_before,
            "the pending plan to finish",
        )
        time.sleep(1.0)
        check(
            "no user, session or job was restored by the late completion",
            store.get_user(leaver_id) is None
            and store.planning_jobs(leaver_id) == []
            and store.planning_session_snapshots(leaver_id) == [],
        )
        gone = g.client().get(f"/plan/{session4['job_id']}")
        check("and the job now answers as missing", gone.status_code == 404)
    finally:
        for server in servers:
            with contextlib.suppress(Exception):
                os.kill(server.proc.pid, signal.SIGCONT)
            with contextlib.suppress(Exception):
                server.kill()
    return facts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.durable_jobs_demo")
    sub = parser.add_subparsers(dest="command", required=True)
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--data-dir", required=True, type=Path)
    serve_parser.add_argument("--port", required=True, type=int)
    serve_parser.add_argument("--hold", action="store_true")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "serve":
        serve(args.data_dir, args.port, hold=args.hold)
        return 0
    os.environ["TRIPWISE_DATA_DIR"] = str(args.data_dir)  # before any app module is imported
    facts = run(args.data_dir)
    failed = [name for name, held in facts.items() if not held]
    print(
        f"\n{len(facts) - len(failed)}/{len(facts)} checks held"
        + (f"; FAILED: {failed}" if failed else "")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
