"""G4 weather: the upstream pin and the dependency audit, executable offline.

The audit performed for this milestone (resolve the tree from the registry
with scripts disabled, then inspect it) is frozen as a lockfile plus these
assertions, so any change to the pinned tree fails the build instead of
silently widening what the project is willing to run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement

from gateway.weather.errors import WeatherGatewayError
from gateway.weather.stdio_transport import StdioWeatherTransport, pinned_upstream_launch
from gateway.weather.upstream_pin import (
    AUDITED_LOCKFILE,
    AUDITED_LOCKFILE_SHA256,
    AUDITED_PACKAGE_COUNT,
    FIXED_SERVER_ENV,
    OFFICIAL_BASE_URLS,
    REQUIRED_NODE_MAJOR,
    UPSTREAM_COMMIT,
    UPSTREAM_LICENSE,
    UPSTREAM_PACKAGE,
    UPSTREAM_TARBALL_INTEGRITY,
    UPSTREAM_VERSION,
)

ALLOWED_LICENSES = {"MIT", "Apache-2.0", "ISC", "BSD-3-Clause"}


def lock() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(AUDITED_LOCKFILE.read_text())
    return data


class TestPinConstants:
    def test_pin_identifies_one_exact_version_and_commit(self) -> None:
        assert UPSTREAM_PACKAGE == "@cyanheads/open-meteo-mcp-server"
        assert UPSTREAM_VERSION == "0.4.1"
        assert re.fullmatch(r"[0-9a-f]{40}", UPSTREAM_COMMIT)
        assert UPSTREAM_LICENSE == "Apache-2.0"
        assert UPSTREAM_TARBALL_INTEGRITY.startswith("sha512-")
        assert REQUIRED_NODE_MAJOR == 24

    def test_base_urls_are_only_official_open_meteo_https_hosts(self) -> None:
        for url in OFFICIAL_BASE_URLS.values():
            assert re.fullmatch(r"https://[a-z\-]*api\.open-meteo\.com", url), url

    def test_fixed_env_has_storage_off_and_no_credentials(self) -> None:
        assert FIXED_SERVER_ENV["CANVAS_PROVIDER_TYPE"] == "none"
        assert FIXED_SERVER_ENV["OPENMETEO_DATAFRAME_DROP_ENABLED"] == "false"
        assert FIXED_SERVER_ENV["MCP_TRANSPORT_TYPE"] == "stdio"
        for key in FIXED_SERVER_ENV:
            assert not re.search(r"(?i)key|token|secret|passw|credential", key), key

    def test_declared_mcp_dependency_excludes_incompatible_1_x(self) -> None:
        pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
        dependency = next(
            Requirement(item)
            for item in pyproject["project"]["dependencies"]
            if Requirement(item).name == "mcp"
        )
        assert dependency.specifier.contains("1.9.9") is False
        assert dependency.specifier.contains("2.3.0") is True


class TestAuditedLockfile:
    def test_lockfile_hash_matches_the_pin(self) -> None:
        assert hashlib.sha256(AUDITED_LOCKFILE.read_bytes()).hexdigest() == AUDITED_LOCKFILE_SHA256

    def test_lockfile_pins_the_server_tarball_integrity(self) -> None:
        entry = lock()["packages"][f"node_modules/{UPSTREAM_PACKAGE}"]
        assert entry["version"] == UPSTREAM_VERSION
        assert entry["integrity"] == UPSTREAM_TARBALL_INTEGRITY
        assert entry["license"] == UPSTREAM_LICENSE
        assert entry["engines"]["node"] == f">={REQUIRED_NODE_MAJOR}.0.0"

    def test_tree_size_is_exactly_what_was_audited(self) -> None:
        packages = {k: v for k, v in lock()["packages"].items() if k}
        assert len(packages) == AUDITED_PACKAGE_COUNT

    def test_no_package_runs_install_scripts(self) -> None:
        assert [k for k, v in lock()["packages"].items() if v.get("hasInstallScript")] == []

    def test_every_package_is_registry_hosted_and_integrity_pinned(self) -> None:
        for name, entry in lock()["packages"].items():
            if not name:
                continue
            assert entry["resolved"].startswith("https://registry.npmjs.org/"), name
            assert entry["integrity"].startswith("sha512-"), name

    def test_only_permissive_licences_and_nothing_deprecated(self) -> None:
        for name, entry in lock()["packages"].items():
            if not name:
                continue
            assert entry.get("license") in ALLOWED_LICENSES, name
            assert not entry.get("deprecated"), name

    def test_the_only_native_code_is_the_optional_duckdb_binding_set(self) -> None:
        optional = {k for k, v in lock()["packages"].items() if v.get("optional")}
        assert optional
        assert all(k.startswith("node_modules/@duckdb/node-bindings-") for k in optional)


def make_install(tmp_path: Path, **overrides: Any) -> tuple[Path, Path]:
    """A fake provisioned tree: audited lockfile + a stub pinned package + a fake node."""
    root = tmp_path / "install"
    pkg = root / "node_modules" / "@cyanheads" / "open-meteo-mcp-server"
    (pkg / "dist").mkdir(parents=True)
    shutil.copy(AUDITED_LOCKFILE, root / "package-lock.json")
    manifest = {
        "name": UPSTREAM_PACKAGE,
        "version": UPSTREAM_VERSION,
        "license": UPSTREAM_LICENSE,
        **overrides,
    }
    (pkg / "package.json").write_text(json.dumps(manifest))
    (pkg / "dist" / "index.js").write_text("// stub")
    node = tmp_path / "node"
    node.write_text("#!/bin/sh\n")
    node.chmod(node.stat().st_mode | stat.S_IXUSR)
    return root, node


class TestPinnedLaunch:
    def test_builds_the_one_approved_launch(self, tmp_path: Path) -> None:
        root, node = make_install(tmp_path)
        launch = pinned_upstream_launch(root, node)
        assert launch.is_pinned_upstream is True
        assert launch.command == str(node.resolve())
        assert launch.args == (
            str(
                (
                    root
                    / "node_modules"
                    / "@cyanheads"
                    / "open-meteo-mcp-server"
                    / "dist"
                    / "index.js"
                ).resolve()
            ),
        )
        assert dict(launch.env) == FIXED_SERVER_ENV
        assert StdioWeatherTransport(launch).origin == "live"

    def test_a_valid_launch_cannot_be_copied_into_live_provenance(
        self, tmp_path: Path
    ) -> None:
        root, node = make_install(tmp_path)
        approved = pinned_upstream_launch(root, node)
        forged = replace(approved, command="/arbitrary/executable")
        assert StdioWeatherTransport(forged).origin == "fixture_synthetic"

    def test_caller_environment_cannot_influence_the_launch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPEN_METEO_API_BASE_URL", "https://evil.example")
        monkeypatch.setenv("OPEN_METEO_API_KEY", "abc")
        root, node = make_install(tmp_path)
        assert dict(pinned_upstream_launch(root, node).env) == FIXED_SERVER_ENV

    @pytest.mark.parametrize(
        "overrides",
        [
            {"version": "0.4.2"},
            {"version": "0.3.9"},
            {"name": "@someone/open-meteo-mcp-server"},
            {"license": "GPL-3.0"},
        ],
    )
    def test_wrong_package_identity_is_refused(
        self, tmp_path: Path, overrides: dict[str, Any]
    ) -> None:
        root, node = make_install(tmp_path, **overrides)
        with pytest.raises(WeatherGatewayError) as exc:
            pinned_upstream_launch(root, node)
        assert exc.value.code == "permission_denied"

    def test_lockfile_drift_is_refused(self, tmp_path: Path) -> None:
        root, node = make_install(tmp_path)
        (root / "package-lock.json").write_text(AUDITED_LOCKFILE.read_text() + " ")
        with pytest.raises(WeatherGatewayError) as exc:
            pinned_upstream_launch(root, node)
        assert exc.value.code == "permission_denied"

    def test_missing_lockfile_package_or_entrypoint_is_refused(self, tmp_path: Path) -> None:
        for victim in ("package-lock.json", "node_modules"):
            root, node = make_install(tmp_path / victim)
            target = root / victim
            shutil.rmtree(target) if target.is_dir() else target.unlink()
            with pytest.raises(WeatherGatewayError):
                pinned_upstream_launch(root, node)
        root, node = make_install(tmp_path / "entry")
        (root / "node_modules/@cyanheads/open-meteo-mcp-server/dist/index.js").unlink()
        with pytest.raises(WeatherGatewayError):
            pinned_upstream_launch(root, node)

    def test_entrypoint_symlink_escaping_the_package_is_refused(self, tmp_path: Path) -> None:
        root, node = make_install(tmp_path)
        outside = tmp_path / "evil.js"
        outside.write_text("// evil")
        entry = root / "node_modules/@cyanheads/open-meteo-mcp-server/dist/index.js"
        entry.unlink()
        os.symlink(outside, entry)
        with pytest.raises(WeatherGatewayError) as exc:
            pinned_upstream_launch(root, node)
        assert exc.value.code == "permission_denied"

    def test_package_symlinked_outside_the_install_root_is_refused(self, tmp_path: Path) -> None:
        root, node = make_install(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        shutil.move(
            str(root / "node_modules" / "@cyanheads" / "open-meteo-mcp-server"), str(elsewhere)
        )
        os.symlink(elsewhere, root / "node_modules" / "@cyanheads" / "open-meteo-mcp-server")
        with pytest.raises(WeatherGatewayError):
            pinned_upstream_launch(root, node)

    def test_relative_paths_and_non_executable_node_are_refused(self, tmp_path: Path) -> None:
        root, node = make_install(tmp_path)
        with pytest.raises(WeatherGatewayError):
            pinned_upstream_launch(Path("relative/install"), node)
        with pytest.raises(WeatherGatewayError):
            pinned_upstream_launch(root, Path("node"))
        node.chmod(0o644)
        with pytest.raises(WeatherGatewayError):
            pinned_upstream_launch(root, node)
