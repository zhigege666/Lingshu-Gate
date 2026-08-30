"""Command-line entry point for Lingshu Gate."""

import argparse
import os
from pathlib import Path
from typing import Sequence

import uvicorn

from lingshu_gate import __version__
from lingshu_gate.config import Settings
from lingshu_gate.logging import configure_logging


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Lingshu Gate API, Console, and MCP gateway")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--host", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=_port, help="HTTP port (default: 8000)")
    parser.add_argument("--data-dir", type=Path, help="Persistent data directory")
    parser.add_argument("--config-dir", type=Path, help="MCP manifest directory")
    parser.add_argument("--workspace", type=Path, help="Allowed workspace root")
    parser.add_argument(
        "--log-level",
        choices=("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"),
        help="Application log level",
    )
    return parser.parse_args(argv)


def _apply_overrides(args: argparse.Namespace) -> None:
    mappings = {
        "LINGSHU_GATE_HOST": args.host,
        "LINGSHU_GATE_PORT": args.port,
        "LINGSHU_GATE_DATA_DIR": args.data_dir,
        "LINGSHU_GATE_CONFIG_DIR": args.config_dir,
        "LINGSHU_GATE_ALLOWED_ROOT": args.workspace,
        "LINGSHU_GATE_LOG_LEVEL": args.log_level,
    }
    for name, value in mappings.items():
        if value is not None:
            os.environ[name] = str(value)


def main() -> None:
    """Start the service using CLI overrides and environment configuration."""

    args = _parse_args()
    _apply_overrides(args)
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    uvicorn.run(
        "lingshu_gate.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        workers=1,
        forwarded_allow_ips=settings.trusted_proxy_ips,
    )


if __name__ == "__main__":
    main()
