"""D1: static guarantees about the deployment artifacts.

These do not need Docker. They pin the properties that matter for safety so an edit to a
Dockerfile, the Compose file, the proxy or a workflow cannot quietly regress them. The
behavioural proof (non-root, read-only, no egress, persistence) is scripts/d1-smoke.sh.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SECRET_WORDS = re.compile(r"(?i)(secret|token|passw|credential|api[_-]?key|private)")


def read(path: Path) -> str:
    return path.read_text()


def dockerfile_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in read(path).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


class TestBackendImage:
    lines = dockerfile_lines(BACKEND / "Dockerfile")
    text = "\n".join(lines)

    def test_base_image_is_pinned_by_digest(self) -> None:
        assert re.search(
            r"^ARG PYTHON_IMAGE=python:3\.14-[a-z\-]+@sha256:[0-9a-f]{64}$", self.text, re.M
        )

    def test_dependencies_install_reproducibly_from_the_hashed_lockfile(self) -> None:
        assert "--require-hashes -r /tmp/requirements.lock" in self.text
        assert "requirements-dev.lock" not in self.text

    def test_runs_as_a_non_root_user(self) -> None:
        users = [line.split()[1] for line in self.lines if line.startswith("USER ")]
        assert users and users[-1] not in {"root", "0"}

    def test_copies_only_named_runtime_packages(self) -> None:
        copies = [line for line in self.lines if line.startswith("COPY ") and "--from=" not in line]
        for line in copies:
            assert not re.search(r"COPY\s+(--\S+\s+)*\.\s", line), line  # never `COPY . .`
        copied = " ".join(copies)
        for forbidden in ("catalogs", ".env", "sqlite", "evals", "raw_overture"):
            assert forbidden not in copied

    def test_no_secret_shaped_env_or_arg_names(self) -> None:
        for line in self.lines:
            if line.startswith(("ENV ", "ARG ")):
                assert not SECRET_WORDS.search(line.split("=", 1)[0]), line

    def test_has_a_readiness_healthcheck_and_the_entrypoint(self) -> None:
        assert "/health/ready" in self.text
        assert 'ENTRYPOINT ["/app/docker-entrypoint.sh"]' in self.text

    def test_mutable_state_has_an_explicit_data_directory(self) -> None:
        assert "TRIPWISE_DATA_DIR=/data" in self.text and 'VOLUME ["/data"]' in self.text

    def test_entrypoint_uses_the_real_startup_path_and_one_worker(self) -> None:
        entry = read(BACKEND / "docker-entrypoint.sh")
        assert "python -m api.runtime_config" in entry
        assert "python -m core.db seed" in entry
        assert "--workers 1" in entry
        assert "CREATE TABLE" not in entry.upper()  # no second schema initialiser

    def test_dockerignore_excludes_state_secrets_and_catalogs(self) -> None:
        ignored = read(BACKEND / ".dockerignore")
        for entry in ("catalogs", "**/.env", "**/*.sqlite*", ".venv", "raw_overture"):
            assert entry in ignored


class TestFrontendImage:
    lines = dockerfile_lines(ROOT / "frontend" / "Dockerfile")
    text = "\n".join(lines)

    def test_is_multi_stage_with_a_pinned_base(self) -> None:
        assert sum(1 for line in self.lines if line.startswith("FROM ")) >= 3
        assert re.search(r"^ARG NODE_IMAGE=node:22-[a-z\-]+@sha256:[0-9a-f]{64}$", self.text, re.M)

    def test_final_stage_is_non_root_and_ships_only_the_standalone_output(self) -> None:
        final = self.text.split("AS runtime", 1)[1]
        assert re.search(r"^USER node$", final, re.M)
        assert ".next/standalone" in final and "node_modules" not in final.replace(
            ".next/standalone", ""
        )
        assert "npm ci" not in final and "npm run build" not in final

    def test_only_public_build_args_and_both_api_modes_are_supported(self) -> None:
        args = [
            line.split()[1].split("=")[0]
            for line in self.lines
            if line.startswith("ARG ") and "IMAGE" not in line
        ]
        assert set(args) == {"NEXT_PUBLIC_API_MODE", "NEXT_PUBLIC_API_BASE_URL"}
        assert "live|mock" in self.text

    def test_live_mode_and_same_origin_api_prefix_are_the_defaults(self) -> None:
        assert "ARG NEXT_PUBLIC_API_MODE=live" in self.text
        assert "ARG NEXT_PUBLIC_API_BASE_URL=/api" in self.text

    def test_nothing_secret_is_baked_in(self) -> None:
        for line in self.lines:
            if line.startswith(("ENV ", "ARG ")):
                assert not SECRET_WORDS.search(line.split("=", 1)[0]), line


class TestCompose:
    compose = yaml.safe_load(read(ROOT / "deploy" / "compose.yaml"))
    services = compose["services"]

    def test_only_the_proxy_publishes_a_port_and_only_on_loopback(self) -> None:
        assert "ports" not in self.services["backend"] and "ports" not in self.services["frontend"]
        assert all(p.startswith("127.0.0.1:") for p in self.services["proxy"]["ports"])

    def test_backend_and_frontend_have_no_outbound_network(self) -> None:
        assert self.services["backend"]["networks"] == ["internal"]
        assert self.services["frontend"]["networks"] == ["internal"]
        assert self.compose["networks"]["internal"]["internal"] is True

    def test_every_service_has_a_healthcheck_and_startup_is_ordered(self) -> None:
        for name, service in self.services.items():
            assert "healthcheck" in service, name
        deps = self.services["proxy"]["depends_on"]
        assert deps["backend"]["condition"] == deps["frontend"]["condition"] == "service_healthy"

    def test_containers_are_locked_down(self) -> None:
        for name, service in self.services.items():
            assert service["read_only"] is True, name
            assert service["cap_drop"] == ["ALL"], name
            assert "no-new-privileges:true" in service["security_opt"], name

    def test_resource_limits_and_a_shutdown_grace_longer_than_uvicorns_drain(self) -> None:
        for name, service in self.services.items():
            assert service["pids_limit"] > 0, name
            assert all("size=" in t for t in service["tmpfs"]), name
        grace = int(self.services["backend"]["stop_grace_period"].rstrip("s"))
        assert grace > 10  # uvicorn --timeout-graceful-shutdown 10

    def test_application_data_lives_on_a_named_volume(self) -> None:
        assert "tripwise-data:/data" in self.services["backend"]["volumes"]
        assert "tripwise-data" in self.compose["volumes"]

    def test_the_stack_is_single_instance_by_construction(self) -> None:
        backend = self.services["backend"]
        assert "deploy" not in backend and "scale" not in backend

    def test_production_mode_and_data_dir_are_set_and_no_live_provider_is_enabled(self) -> None:
        env = self.services["backend"]["environment"]
        assert env["TRIPWISE_ENV"] == "production" and env["TRIPWISE_DATA_DIR"] == "/data"
        assert not [k for k in env if k.endswith(("_ENABLED", "_LIVE_ENABLED"))]

    def test_no_secret_value_is_hardcoded(self) -> None:
        for service in self.services.values():
            env = service.get("environment", {})
            for key, value in env.items() if isinstance(env, dict) else []:
                assert not (SECRET_WORDS.search(key) and value), key

    def test_third_party_image_is_pinned_by_digest(self) -> None:
        assert re.search(r"@sha256:[0-9a-f]{64}$", self.services["proxy"]["image"])

    def test_catalogs_are_an_explicit_read_only_overlay_never_baked_in(self) -> None:
        overlay = yaml.safe_load(read(ROOT / "deploy" / "compose.catalogs.yaml"))
        mounts = overlay["services"]["backend"]["volumes"]
        assert any(m.endswith(":/app/catalogs:ro") for m in mounts)


class TestProxy:
    conf = read(ROOT / "deploy" / "nginx" / "default.conf")

    def test_routes_api_with_prefix_stripped_and_everything_else_to_the_frontend(self) -> None:
        assert re.search(
            r"location /api/ \{[^}]*rewrite \^/api/\(\.\*\)\$ /\$1 break;[^}]*"
            r"proxy_pass \$tripwise_backend;",
            self.conf,
            re.S,
        )
        assert re.search(r"location / \{[^}]*proxy_pass \$tripwise_frontend;", self.conf, re.S)

    def test_upstreams_are_resolved_per_request_not_frozen_at_start(self) -> None:
        assert "resolver 127.0.0.11" in self.conf
        assert "set $tripwise_backend  http://backend:8000;" in self.conf
        assert "set $tripwise_frontend http://frontend:3000;" in self.conf
        assert "upstream " not in self.conf  # static upstream blocks resolve once, at start

    def test_prefix_broken_interactive_docs_are_not_exposed(self) -> None:
        assert re.search(r"location ~ \^/api/\(docs\|redoc\)\(/\|\$\) \{\s*return 404;", self.conf)

    def test_never_widens_cors_or_strips_cookie_security(self) -> None:
        assert "Access-Control-Allow-Origin" not in self.conf
        assert "proxy_cookie" not in self.conf


class TestEnvironmentTemplate:
    template = read(ROOT / "deploy" / ".env.example")

    def test_contains_names_and_explanations_only(self) -> None:
        for line in self.template.splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                raise AssertionError(f"uncommented assignment in a template: {line!r}")

    def test_documents_every_environment_variable_the_backend_reads(self) -> None:
        documented = self.template + read(BACKEND / ".env.example")
        used: set[str] = set()
        for path in BACKEND.rglob("*.py"):
            if ".venv" in path.parts or "evals" in path.parts:
                continue
            used |= set(re.findall(r"""["'](TRIPWISE_[A-Z0-9_]+)["']""", read(path)))
        missing = sorted(v for v in used if v not in documented)
        assert not missing, f"undocumented environment variables: {missing}"

    def test_separates_the_kinds_of_configuration(self) -> None:
        for heading in (
            "1. Required production configuration",
            "2. Compose-level settings",
            "3. Optional application configuration",
            "4. Optional local-development only",
            "5. Live-provider variables",
            "6. Kill switches",
        ):
            assert heading in self.template, heading


class TestLockfiles:
    def test_every_pinned_requirement_has_hashes(self) -> None:
        for name in ("requirements.lock", "requirements-dev.lock"):
            text = read(BACKEND / name)
            entries = re.findall(r"^([A-Za-z0-9_.\-]+)==", text, re.M)
            assert entries
            assert text.count("--hash=sha256:") >= len(entries)

    def test_runtime_dependencies_are_all_locked(self) -> None:
        import tomllib

        deps = tomllib.loads(read(BACKEND / "pyproject.toml"))["project"]["dependencies"]
        locked = {
            m.lower().replace("_", "-")
            for m in re.findall(r"^([A-Za-z0-9_.\-]+)==", read(BACKEND / "requirements.lock"), re.M)
        }
        for dep in deps:
            name = re.split(r"[<>=!~\[ ]", dep, maxsplit=1)[0].lower().replace("_", "-")
            assert name in locked, name

    def test_uvicorn_is_a_declared_runtime_dependency(self) -> None:
        assert (
            "uvicorn"
            in read(BACKEND / "pyproject.toml").split("[project.optional-dependencies]")[0]
        )


class TestWorkflows:
    files = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

    def test_actions_are_pinned_to_full_commit_shas(self) -> None:
        assert self.files
        for path in self.files:
            for use in re.findall(r"uses:\s*(\S+)", read(path)):
                assert re.search(r"@[0-9a-f]{40}$", use), (path.name, use)

    def test_permissions_are_read_only_and_no_secrets_or_writes(self) -> None:
        for path in self.files:
            text = read(path)
            doc = yaml.safe_load(text)
            assert doc["permissions"] == {"contents": "read"}, path.name
            assert "secrets." not in text, path.name
            assert not re.search(r"git (push|commit|add)\b", text), path.name
            assert "contents: write" not in text and "pull-requests: write" not in text

    def test_required_ci_covers_the_agreed_checks(self) -> None:
        text = read(ROOT / ".github" / "workflows" / "ci.yml")
        doc = yaml.safe_load(text)
        triggers = doc.get("on") or doc.get(True)
        assert "pull_request" in triggers and triggers["push"]["branches"] == ["main"]
        assert set(doc["jobs"]) == {"backend", "frontend", "contract-drift", "containers-and-smoke"}
        for needle in (
            "make seed",
            "pytest",
            "mypy --strict",
            "ruff check",
            "tsc --noEmit",
            "vitest run",
            "npm run lint",
            "token-lint",
            "no-dead-classes",
            "npm run build",
            "check-contract-drift.sh",
            "compose -p tripwise-d1",
            "scripts/d1-smoke.sh",
            "--require-hashes",
        ):
            assert needle in text, needle

    def test_the_full_browser_suite_is_a_separate_non_pr_workflow(self) -> None:
        doc = yaml.safe_load(read(ROOT / ".github" / "workflows" / "full-browser-suite.yml"))
        triggers = doc.get("on") or doc.get(True)
        assert "pull_request" not in triggers and "workflow_dispatch" in triggers


class TestMakefile:
    text = read(ROOT / "Makefile")

    def test_default_interpreter_is_never_bare_python(self) -> None:
        line = next(line for line in self.text.splitlines() if line.startswith("PY ?="))
        assert "python3" in line and line.strip() != "PY ?= python"

    def test_bootstrap_and_deployment_targets_exist(self) -> None:
        for target in (
            "setup:",
            "lock:",
            "contract-check:",
            "docker-build:",
            "compose-up:",
            "d1-smoke:",
        ):
            assert target in self.text


class TestWorkflowShellAndSkipAccounting:
    """The Critical review finding: `pytest | tee` under GitHub's default `bash -e` (no
    pipefail) reports tee's exit status, so a red suite would pass."""

    files = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

    def test_every_job_runs_steps_under_bash_with_pipefail(self) -> None:
        for path in self.files:
            doc = yaml.safe_load(read(path))
            workflow_shell = (doc.get("defaults") or {}).get("run", {}).get("shell")
            for name, job in doc["jobs"].items():
                job_shell = ((job.get("defaults") or {}).get("run") or {}).get("shell")
                assert (job_shell or workflow_shell) == "bash", (path.name, name)

    def test_no_step_overrides_the_shell_with_something_weaker(self) -> None:
        for path in self.files:
            doc = yaml.safe_load(read(path))
            for job in doc["jobs"].values():
                for step in job["steps"]:
                    assert step.get("shell", "bash") == "bash", (path.name, step.get("name"))

    @staticmethod
    def _run_accounting(tmp_path: Path, pytest_output: str) -> tuple[int, str]:
        import os
        import subprocess
        import sys

        text = read(ROOT / ".github" / "workflows" / "ci.yml")
        match = re.search(r"python3 - <<'PY'\n(.*?)\n\s*PY\n", text, re.S)
        assert match
        code = "\n".join(
            line[10:] if line.startswith(" " * 10) else line for line in match.group(1).splitlines()
        )
        (tmp_path / "pytest.txt").write_text(pytest_output)
        env = {
            **os.environ,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        }
        result = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True
        )
        return result.returncode, result.stdout + result.stderr

    def test_catalog_skips_are_recognised_by_their_reason(self, tmp_path: Path) -> None:
        out = (
            "SKIPPED [19] evals/test_audit_regional_search.py:36: regional catalog artifacts "
            "(backend/catalogs/active_*-core.json) are not provisioned; see docs\n"
            "SKIPPED [1] evals/test_region_isolation.py:47: requires both real catalogs built\n"
            "SKIPPED [1] evals/test_cp1_boundaries.py:74: CP1_MERGE_BASE is required\n"
        )
        code, text = self._run_accounting(tmp_path, out)
        assert code == 0, text
        assert "skipped because the untracked regional catalogs are not provisioned: **20**" in text

    def test_an_unrelated_skip_in_a_file_named_catalog_is_not_hidden(self, tmp_path: Path) -> None:
        out = (
            "SKIPPED [1] evals/test_cp1_boundaries.py:74: CP1_MERGE_BASE is required\n"
            "SKIPPED [2] evals/test_catalog_cache.py:10: flaky on this runner\n"
        )
        code, text = self._run_accounting(tmp_path, out)
        assert code != 0 and "unexpected skipped tests" in text

    def test_the_real_github_runner_skip_output_is_accounted_correctly(
        self, tmp_path: Path
    ) -> None:
        """Regression for the first real CI run: test_i7_gate parametrises over activated
        catalogs, so with none it produces 'got empty parameter set for (catalog_id, data)'
        skips. Those are catalog-caused; only the CP1 merge-base skip is 'other'."""
        guard = (
            "regional catalog artifacts (backend/catalogs/active_*-core.json) are not "
            "provisioned; see docs/DEPLOYMENT.md"
        )
        empty = "got empty parameter set for (catalog_id, data)"
        rows = [
            (5, "test_audit_regional_search.py:35", guard),
            (6, "test_audit_taxonomy_retrieval.py:53", guard),
            (
                1,
                "test_cp1_boundaries.py:74",
                "CP1_MERGE_BASE is required for committed-diff assertions",
            ),
            (1, "test_i7_gate.py:47", "requires at least one real catalog built"),
            (1, "test_i7_gate.py:54", empty),
            (1, "test_i7_gate.py:62", empty),
            (1, "test_i7_gate.py:67", empty),
            (1, "test_i7_gate.py:78", empty),
            (1, "test_i7_gate.py:102", "requires at least two real catalogs built"),
            (
                1,
                "test_region_isolation.py:47",
                "requires both real catalogs built (backend/catalogs)",
            ),
        ]
        runner_output = "\n".join(f"SKIPPED [{n}] evals/{where}: {why}" for n, where, why in rows)
        code, text = TestWorkflowShellAndSkipAccounting._run_accounting(tmp_path, runner_output)
        assert code == 0, text
        assert "skipped for any other reason: **1**" in text

    def test_an_unrelated_empty_parameter_set_skip_is_still_flagged(self, tmp_path: Path) -> None:
        out = (
            "SKIPPED [1] evals/test_cp1_boundaries.py:74: CP1_MERGE_BASE is required\n"
            "SKIPPED [1] evals/test_x.py:3: got empty parameter set for (case_id, payload)\n"
        )
        code, text = TestWorkflowShellAndSkipAccounting._run_accounting(tmp_path, out)
        assert code != 0 and "unexpected skipped tests" in text
