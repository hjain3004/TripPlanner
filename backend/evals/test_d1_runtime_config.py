"""D1: startup validation of genuinely required deployment configuration.

Errors name variables and fixed problems only - never values - so a misconfigured
secret can never be echoed into logs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from api.runtime_config import ConfigError, assert_valid_runtime_config, validate_runtime_config

BACKEND = Path(__file__).parent.parent


def names(env: dict[str, str]) -> set[str]:
    return {issue.variable for issue in validate_runtime_config(env)}


def prod(data_dir: Path, **extra: str) -> dict[str, str]:
    return {"TRIPWISE_ENV": "production", "TRIPWISE_DATA_DIR": str(data_dir), **extra}


class TestDevelopmentIsPermissive:
    def test_empty_environment_is_valid(self) -> None:
        assert validate_runtime_config({}) == []

    def test_missing_live_provider_credentials_never_block_startup(self) -> None:
        assert validate_runtime_config({"TRIPWISE_ENV": "development"}) == []


class TestProductionRequirements:
    def test_valid_minimal_production_config(self, tmp_path: Path) -> None:
        assert validate_runtime_config(prod(tmp_path)) == []

    def test_sample_mode_needs_no_provider_credentials(self, tmp_path: Path) -> None:
        env = prod(tmp_path)
        for key in ("TRIPWISE_LLM_API_KEY", "TRIPWISE_TRIPADVISOR_API_KEY"):
            assert key not in env
        assert validate_runtime_config(env) == []

    def test_data_dir_is_required(self) -> None:
        assert names({"TRIPWISE_ENV": "production"}) == {"TRIPWISE_DATA_DIR"}

    def test_data_dir_must_be_absolute_existing_and_a_directory(self, tmp_path: Path) -> None:
        assert names(prod(Path("relative/dir"))) == {"TRIPWISE_DATA_DIR"}
        assert names(prod(tmp_path / "missing")) == {"TRIPWISE_DATA_DIR"}
        a_file = tmp_path / "file"
        a_file.write_text("x")
        assert names(prod(a_file)) == {"TRIPWISE_DATA_DIR"}

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
    def test_data_dir_must_be_writable(self, tmp_path: Path) -> None:
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        try:
            assert names(prod(locked)) == {"TRIPWISE_DATA_DIR"}
        finally:
            locked.chmod(0o700)

    def test_unknown_environment_name_is_rejected(self) -> None:
        assert names({"TRIPWISE_ENV": "staging"}) == {"TRIPWISE_ENV"}


class TestCorsOrigins:
    @pytest.mark.parametrize(
        "value",
        ["*", "https://a.example/path", "ftp://a.example", "a.example", "https://*.example", ","],
    )
    def test_malformed_origins_are_rejected(self, value: str) -> None:
        assert "TRIPWISE_CORS_ORIGINS" in names({"TRIPWISE_CORS_ORIGINS": value})

    def test_well_formed_origins_are_accepted(self) -> None:
        env = {"TRIPWISE_CORS_ORIGINS": "https://app.example, http://localhost:3000"}
        assert validate_runtime_config(env) == []

    @pytest.mark.parametrize(
        "value", ["http://localhost:3000/", "http://[::1", "http://a.example:99999"]
    )
    def test_trailing_slash_and_unparseable_origins_are_rejected_without_crashing(
        self, value: str
    ) -> None:
        assert names({"TRIPWISE_CORS_ORIGINS": value}) == {"TRIPWISE_CORS_ORIGINS"}


class TestLiveProvidersStayOff:
    @pytest.mark.parametrize(
        "flag", ["TRIPWISE_GONDOLA_LIVE_ENABLED", "TRIPWISE_OPEN_METEO_ENABLED"]
    )
    def test_production_refuses_to_start_with_a_live_provider_enabled(
        self, tmp_path: Path, flag: str
    ) -> None:
        assert names(prod(tmp_path, **{flag: "1"})) == {flag}

    def test_a_kill_switch_makes_the_enable_flag_moot(self, tmp_path: Path) -> None:
        env = prod(
            tmp_path,
            TRIPWISE_GONDOLA_LIVE_ENABLED="1",
            TRIPWISE_GONDOLA_KILL_SWITCH="1",
        )
        assert validate_runtime_config(env) == []

    def test_other_live_capable_switches_are_refused_in_production_too(
        self, tmp_path: Path
    ) -> None:
        assert names(prod(tmp_path, TRIPWISE_INTERVIEW_LLM_ZERO_SPEND_CONFIRMED="1")) == {
            "TRIPWISE_INTERVIEW_LLM_ZERO_SPEND_CONFIRMED"
        }
        assert names(prod(tmp_path, TRIPWISE_POST_PLAN_LLM_ZERO_SPEND_CONFIRMED="1")) == {
            "TRIPWISE_POST_PLAN_LLM_ZERO_SPEND_CONFIRMED"
        }
        assert names(prod(tmp_path, TRIPWISE_TRIPADVISOR_API_KEY="x")) == {
            "TRIPWISE_TRIPADVISOR_API_KEY"
        }
        killed = prod(
            tmp_path, TRIPWISE_TRIPADVISOR_API_KEY="x", TRIPWISE_TRIPADVISOR_KILL_SWITCH="1"
        )
        assert validate_runtime_config(killed) == []
        # The CP3 flag is exactly "1"; any other value leaves the role off.
        assert (
            validate_runtime_config(prod(tmp_path, TRIPWISE_INTERVIEW_LLM_ZERO_SPEND_CONFIRMED="0"))
            == []
        )

    def test_development_may_enable_providers_for_offline_experiments(self) -> None:
        assert validate_runtime_config({"TRIPWISE_GONDOLA_LIVE_ENABLED": "1"}) == []


class TestNumericSettings:
    @pytest.mark.parametrize("value", ["abc", "0", "-1", "1.5", "²", "٣"])
    def test_llm_max_calls_must_be_a_positive_integer(self, value: str) -> None:
        assert "TRIPWISE_LLM_MAX_CALLS" in names({"TRIPWISE_LLM_MAX_CALLS": value})


class TestErrorsNeverEchoValues:
    def test_error_text_contains_names_only(self, tmp_path: Path) -> None:
        secret = "SUPER-SECRET-VALUE-123"
        env = {
            "TRIPWISE_ENV": "production",
            "TRIPWISE_DATA_DIR": f"relative/{secret}",
            "TRIPWISE_CORS_ORIGINS": f"{secret}",
            "TRIPWISE_LLM_MAX_CALLS": secret,
            "TRIPWISE_LLM_API_KEY": secret,
        }
        with pytest.raises(ConfigError) as exc:
            assert_valid_runtime_config(env)
        text = (
            str(exc.value)
            + repr(exc.value)
            + " ".join(f"{i.variable}:{i.problem}" for i in exc.value.issues)
        )
        assert secret not in text
        assert "TRIPWISE_DATA_DIR" in text and "TRIPWISE_CORS_ORIGINS" in text

    def test_valid_config_does_not_raise(self, tmp_path: Path) -> None:
        assert_valid_runtime_config(prod(tmp_path))


class TestCommandLineCheck:
    def _run(self, env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TRIPWISE_")}
        env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-m", "api.runtime_config"],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_exit_zero_when_valid(self, tmp_path: Path) -> None:
        assert self._run(prod(tmp_path)).returncode == 0

    def test_exit_nonzero_and_names_the_variable_when_invalid(self) -> None:
        secret = "do-not-print-me"
        result = self._run({"TRIPWISE_ENV": "production", "TRIPWISE_CORS_ORIGINS": secret})
        assert result.returncode != 0
        assert "TRIPWISE_DATA_DIR" in result.stderr and "TRIPWISE_CORS_ORIGINS" in result.stderr
        assert secret not in result.stdout + result.stderr
