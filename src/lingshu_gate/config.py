"""Runtime configuration for Lingshu Gate."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from lingshu_gate import __version__


def _platform_paths() -> tuple[Path, Path, Path]:
    """Return secure per-user defaults for native installations."""

    home = Path.home()
    if os.name == "nt":
        data_base = Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local"))
        config_base = Path(os.getenv("APPDATA", home / "AppData" / "Roaming"))
        data_dir = data_base / "Lingshu Gate"
        config_dir = config_base / "Lingshu Gate" / "config" / "mcp.d"
    elif sys.platform == "darwin":
        data_dir = home / "Library" / "Application Support" / "Lingshu Gate"
        config_dir = data_dir / "config" / "mcp.d"
    else:
        state_base = Path(os.getenv("XDG_STATE_HOME", home / ".local" / "state"))
        config_base = Path(os.getenv("XDG_CONFIG_HOME", home / ".config"))
        data_dir = state_base / "lingshu-gate"
        config_dir = config_base / "lingshu-gate" / "mcp.d"
    return data_dir, config_dir, data_dir / "workspace"


_DEFAULT_DATA_DIR, _DEFAULT_CONFIG_DIR, _DEFAULT_ALLOWED_ROOT = _platform_paths()


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    service_name: str = "Lingshu Gate"
    version: str = __version__
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_root: Path = _DEFAULT_ALLOWED_ROOT
    max_read_bytes: int = 256 * 1024
    config_dir: Path = _DEFAULT_CONFIG_DIR
    data_dir: Path = _DEFAULT_DATA_DIR
    db_type: str = "sqlite"
    db_url: str = f"sqlite:///{_DEFAULT_DATA_DIR / 'gate.db'}"
    # 访问治理是 Gate 的安全基线；需要无鉴权调试时必须显式关闭。
    auth_enabled: bool = True
    auth_session_cookie_name: str = "lingshu_gate_session"
    auth_session_ttl_hours: int = 24
    # 本地 HTTP 默认兼容；TLS 反向代理或公网部署必须显式启用 Secure。
    auth_cookie_secure: bool = False
    # Only accept forwarded headers from an explicitly trusted local proxy by default.
    trusted_proxy_ips: str = "127.0.0.1"
    log_level: str = "INFO"
    mcp_request_timeout_seconds: int = 30
    mcp_startup_timeout_seconds: int = 30
    mcp_log_payloads: bool = False
    # Browser-originated MCP requests are accepted only from this explicit list.
    # Non-browser clients normally omit Origin and are unaffected.
    mcp_allowed_origins: str = ""
    # local 可执行受管进程；安全 Core 只连接 external HTTP MCP。
    runtime_role: str = "local"
    mcp_gateway_enabled: bool = True
    system_debug_mcp_enabled: bool = True
    docker_bin: str = "docker"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("LINGSHU_GATE_DATA_DIR", str(cls.data_dir))).resolve()
        runtime_role = os.getenv("LINGSHU_GATE_RUNTIME_ROLE", cls.runtime_role).strip().lower()
        if runtime_role not in {"local", "core"}:
            raise ValueError("LINGSHU_GATE_RUNTIME_ROLE must be one of local, core")
        db_type = os.getenv("LINGSHU_GATE_DB_TYPE", cls.db_type).strip().lower()
        db_url = os.getenv("LINGSHU_GATE_DB_URL", f"sqlite:///{data_dir / 'gate.db'}").strip()
        if db_type != "sqlite":
            raise ValueError("LINGSHU_GATE_DB_TYPE must be sqlite")
        if not db_url.startswith("sqlite:///") or db_url == "sqlite:///" or any(
            marker in db_url for marker in ("?", "#")
        ):
            raise ValueError("LINGSHU_GATE_DB_URL must be a SQLite file URL")
        allowed_root_default = data_dir / "workspace" if "LINGSHU_GATE_DATA_DIR" in os.environ else cls.allowed_root
        return cls(
            service_name=cls.service_name,
            version=cls.version,
            host=os.getenv("LINGSHU_GATE_HOST", cls.host),
            port=int(os.getenv("LINGSHU_GATE_PORT", str(cls.port))),
            allowed_root=Path(os.getenv("LINGSHU_GATE_ALLOWED_ROOT", str(allowed_root_default))).resolve(),
            max_read_bytes=int(os.getenv("LINGSHU_GATE_MAX_READ_BYTES", str(cls.max_read_bytes))),
            config_dir=Path(os.getenv("LINGSHU_GATE_CONFIG_DIR", str(cls.config_dir))).resolve(),
            data_dir=data_dir,
            db_type=db_type,
            db_url=db_url,
            auth_enabled=os.getenv("LINGSHU_GATE_AUTH_ENABLED", str(cls.auth_enabled)).lower()
            in {"1", "true", "yes", "on"},
            auth_session_cookie_name=os.getenv("LINGSHU_GATE_AUTH_COOKIE_NAME", cls.auth_session_cookie_name),
            auth_session_ttl_hours=int(os.getenv("LINGSHU_GATE_AUTH_SESSION_TTL_HOURS", str(cls.auth_session_ttl_hours))),
            auth_cookie_secure=os.getenv(
                "LINGSHU_GATE_AUTH_COOKIE_SECURE",
                str(cls.auth_cookie_secure),
            ).lower()
            in {"1", "true", "yes", "on"},
            trusted_proxy_ips=os.getenv(
                "LINGSHU_GATE_TRUSTED_PROXY_IPS",
                cls.trusted_proxy_ips,
            ),
            log_level=os.getenv("LINGSHU_GATE_LOG_LEVEL", cls.log_level).upper(),
            mcp_request_timeout_seconds=int(
                os.getenv("LINGSHU_GATE_REQUEST_TIMEOUT_SECONDS", str(cls.mcp_request_timeout_seconds))
            ),
            mcp_startup_timeout_seconds=int(
                os.getenv("LINGSHU_GATE_STARTUP_TIMEOUT_SECONDS", str(cls.mcp_startup_timeout_seconds))
            ),
            mcp_log_payloads=os.getenv(
                "LINGSHU_GATE_LOG_PAYLOADS",
                str(cls.mcp_log_payloads),
            ).lower()
            in {"1", "true", "yes", "on"},
            mcp_allowed_origins=os.getenv(
                "LINGSHU_GATE_MCP_ALLOWED_ORIGINS",
                cls.mcp_allowed_origins,
            ),
            runtime_role=runtime_role,
            mcp_gateway_enabled=os.getenv(
                "LINGSHU_GATE_MCP_GATEWAY_ENABLED",
                str(cls.mcp_gateway_enabled),
            ).lower()
            in {"1", "true", "yes", "on"},
            system_debug_mcp_enabled=os.getenv(
                "LINGSHU_GATE_SYSTEM_DEBUG_MCP_ENABLED",
                str(cls.system_debug_mcp_enabled),
            ).lower()
            in {"1", "true", "yes", "on"},
            docker_bin=os.getenv("LINGSHU_GATE_DOCKER_BIN", cls.docker_bin),
        )
