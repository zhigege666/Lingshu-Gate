from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from lingshu_gate import __version__
from lingshu_gate.cli import _apply_overrides, _parse_args, main
from lingshu_gate.config import Settings


def test_version_flag_uses_single_version_source(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["lingshu-gate", "--version"])

    with pytest.raises(SystemExit) as exc_info:
        _parse_args()

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"lingshu-gate {__version__}"


@pytest.mark.parametrize(
    ("arguments", "expected_code"),
    [(["--version"], 0), (["--help"], 0), (["--port", "70000"], 2)],
    ids=["version", "help", "usage-error"],
)
def test_module_and_installed_console_entrypoints_share_product_identity(
    tmp_path: Path, arguments: list[str], expected_code: int,
) -> None:
    console = Path(sysconfig.get_path("scripts")) / ("lingshu-gate.exe" if os.name == "nt" else "lingshu-gate")
    assert console.is_file(), "Run uv sync to install the declared console entry point before testing"
    environment = {
        **os.environ,
        "LINGSHU_GATE_DB_URL": "not-a-service-database",
        "NO_COLOR": "1",
    }
    results = [
        subprocess.run(
            command + arguments, cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=20,
        )
        for command in ([sys.executable, "-m", "lingshu_gate.cli"], [str(console)])
    ]
    module, installed = results
    assert (module.returncode, module.stdout, module.stderr) == (
        installed.returncode, installed.stdout, installed.stderr
    )
    assert module.returncode == expected_code
    if arguments == ["--version"]:
        assert module.stdout.strip() == f"lingshu-gate {__version__}"
    else:
        output = module.stderr if expected_code else module.stdout
        assert output.startswith("usage: lingshu-gate ")
    assert "not-a-service-database" not in module.stdout + module.stderr


def test_cli_overrides_are_applied_before_settings_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    workspace = tmp_path / "workspace"
    args = _parse_args(
        [
            "--host",
            "127.0.0.2",
            "--port",
            "8123",
            "--data-dir",
            str(data_dir),
            "--config-dir",
            str(config_dir),
            "--workspace",
            str(workspace),
            "--log-level",
            "DEBUG",
        ]
    )
    for name in (
        "LINGSHU_GATE_HOST",
        "LINGSHU_GATE_PORT",
        "LINGSHU_GATE_DATA_DIR",
        "LINGSHU_GATE_CONFIG_DIR",
        "LINGSHU_GATE_ALLOWED_ROOT",
        "LINGSHU_GATE_LOG_LEVEL",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("LINGSHU_GATE_RUNTIME_ROLE", "local")

    _apply_overrides(args)
    settings = Settings.from_env()

    assert settings.host == "127.0.0.2"
    assert settings.port == 8123
    assert settings.data_dir == data_dir.resolve()
    assert settings.config_dir == config_dir.resolve()
    assert settings.allowed_root == workspace.resolve()
    assert settings.log_level == "DEBUG"


def test_native_defaults_are_loopback_and_user_local() -> None:
    settings = Settings()

    assert settings.host == "127.0.0.1"
    assert settings.data_dir != Path("/data")
    assert settings.config_dir != Path("/config/mcp.d")
    assert settings.allowed_root != Path("/workspace")


def test_invalid_port_is_rejected() -> None:
    with pytest.raises(SystemExit) as exc_info:
        _parse_args(["--port", "70000"])

    assert exc_info.value.code == 2


def test_runtime_role_rejects_noncanonical_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINGSHU_GATE_RUNTIME_ROLE", "distributed")

    with pytest.raises(
        ValueError,
        match="LINGSHU_GATE_RUNTIME_ROLE must be one of local, core",
    ):
        Settings.from_env()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("LINGSHU_GATE_DB_TYPE", "remote", "LINGSHU_GATE_DB_TYPE must be sqlite"),
        (
            "LINGSHU_GATE_DB_URL",
            "https://user:secret@example.invalid/gate",
            "LINGSHU_GATE_DB_URL must be a SQLite file URL",
        ),
        (
            "LINGSHU_GATE_DB_URL",
            "sqlite:////tmp/gate.db?token=secret",
            "LINGSHU_GATE_DB_URL must be a SQLite file URL",
        ),
    ],
)
def test_database_environment_rejects_unsupported_or_secret_bearing_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        Settings.from_env()


def test_main_passes_only_configured_proxy_sources_to_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(sys, "argv", ["lingshu-gate"])
    monkeypatch.setenv("LINGSHU_GATE_TRUSTED_PROXY_IPS", "10.0.0.12")
    monkeypatch.setattr("lingshu_gate.cli.configure_logging", lambda _level: None)
    monkeypatch.setattr("lingshu_gate.cli.uvicorn.run", lambda *args, **kwargs: captured.update(kwargs))

    main()

    assert captured["forwarded_allow_ips"] == "10.0.0.12"
    assert captured["workers"] == 1
