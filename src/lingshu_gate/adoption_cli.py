"""Explicit service commands, separate from Core startup."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections.abc import Sequence

import uvicorn


def port(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be an integer") from None
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return number


def main(argv: Sequence[str]) -> None:
    parser = argparse.ArgumentParser(prog="lingshu-gate", description="Gate service commands", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo-server", help="Run the bounded in-memory demo MCP")
    demo.add_argument("--host", choices=("127.0.0.1", "::1"), default="127.0.0.1")
    demo.add_argument("--port", type=port, default=18880)
    openapi = commands.add_parser("openapi", help="Validate or serve a fixed OpenAPI snapshot", allow_abbrev=False)
    actions = openapi.add_subparsers(dest="action", required=True)
    for action in ("validate", "serve"):
        sub = actions.add_parser(action, allow_abbrev=False)
        sub.add_argument("--schema", type=Path, required=True)
        sub.add_argument("--config", type=Path, required=True)
        if action == "serve":
            sub.add_argument("--host", default="127.0.0.1")
            sub.add_argument("--port", type=port, default=18881)
            sub.add_argument("--allowed-host", action="append", default=[])
            sub.add_argument("--allowed-origin", action="append", default=[])
            sub.add_argument("--token-file", type=Path)
            sub.add_argument("--tls-cert", type=Path)
            sub.add_argument("--tls-key", type=Path)
            sub.add_argument("--ca-file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "demo-server":
        from lingshu_gate.demo_mcp import create_demo_app

        uvicorn.run(create_demo_app(), host=args.host, port=args.port, workers=1,
                    forwarded_allow_ips="", access_log=False)
    elif args.command == "openapi":
        from lingshu_gate.service_io import ServiceConfigError, load_document, loopback, secret_file
        from lingshu_gate.openapi_contract import compile_openapi

        try:
            contract = compile_openapi(load_document(args.schema), load_document(args.config))
            if args.action == "validate":
                print(json.dumps(contract.preview(), ensure_ascii=False, indent=2))
                return
            if bool(args.tls_cert) != bool(args.tls_key):
                raise ServiceConfigError("tls_certificate_and_key_required")
            if not loopback(args.host) and not (args.tls_cert and args.token_file and args.allowed_host):
                raise ServiceConfigError("remote_listener_requires_tls_authentication_and_allowed_host")
            hosts = args.allowed_host or [f"127.0.0.1:{args.port}", f"localhost:{args.port}", f"[::1]:{args.port}"]
            if any("*" in host or "/" in host or any(c.isspace() for c in host) for host in hosts):
                raise ServiceConfigError("allowed_host_invalid")
            if args.token_file:
                secret_file(args.token_file)
            for credential in contract.credential_files.values():
                secret_file(Path(credential))
            from lingshu_gate.openapi_adapter import create_openapi_app

            uvicorn.run(create_openapi_app(contract, hosts=hosts, origins=args.allowed_origin, token_file=args.token_file,
                ca_file=args.ca_file), host=args.host, port=args.port, workers=1, forwarded_allow_ips="", access_log=False,
                ssl_certfile=str(args.tls_cert) if args.tls_cert else None, ssl_keyfile=str(args.tls_key) if args.tls_key else None)
        except ServiceConfigError as error:
            print(json.dumps({"error": error.detail()}))
            raise SystemExit(2) from None
