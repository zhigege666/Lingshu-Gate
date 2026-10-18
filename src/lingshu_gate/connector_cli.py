"""Explicit relay, private agent and authenticated status commands."""
from __future__ import annotations

import argparse
import asyncio
import json
import ssl
from collections.abc import Sequence
from pathlib import Path

import httpx2
import uvicorn

from lingshu_gate.service_io import ServiceConfigError, fixed_url, load_document, parse_document, secret_file
from lingshu_gate.connector_protocol import FRAME_BYTES, AgentConfig, RelayConfig, parse_model


def main(argv: Sequence[str]) -> None:
    parser = argparse.ArgumentParser(prog="lingshu-gate connector", allow_abbrev=False,
        description="Explicit fixed-target HTTP MCP relay and outbound private agent")
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("relay", "agent"):
        sub = actions.add_parser(action, allow_abbrev=False)
        sub.add_argument("--config", type=Path, required=True)
    status = actions.add_parser("status", allow_abbrev=False)
    status.add_argument("--url", required=True, help="Full HTTPS or loopback HTTP /connector/status URL")
    status.add_argument("--token-file", type=Path, required=True)
    status.add_argument("--ca-file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "relay":
            from lingshu_gate.connector_relay import create_relay_app

            relay = parse_model(RelayConfig, load_document(args.config))
            uvicorn.run(create_relay_app(relay), host=relay.host, port=relay.port, workers=1,
                forwarded_allow_ips="", access_log=False, ws_max_size=FRAME_BYTES, ws_max_queue=4,
                ws_per_message_deflate=False, ws_ping_interval=15, ws_ping_timeout=10,
                limit_concurrency=128, timeout_graceful_shutdown=5,
                ssl_certfile=relay.tls_cert_file, ssl_keyfile=relay.tls_key_file)
        elif args.action == "agent":
            from lingshu_gate.connector_agent import ConnectorAgent

            config = parse_model(AgentConfig, load_document(args.config))
            asyncio.run(ConnectorAgent(config).run())
        else:
            url = fixed_url(args.url)
            if not url.endswith("/connector/status"):
                raise ServiceConfigError("connector_status_url_required")
            with httpx2.Client(verify=ssl.create_default_context(cafile=args.ca_file), timeout=10,
                              trust_env=False, follow_redirects=False) as client:
                with client.stream("GET", url, headers={"Authorization": "Bearer " + secret_file(args.token_file)}) as response:
                    if response.status_code != 200:
                        raise ServiceConfigError("connector_status_http_" + str(response.status_code))
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 65536:
                            raise ServiceConfigError("connector_status_size_limit")
                    print(json.dumps(parse_document(bytes(data), yaml_allowed=False, limit=65536), indent=2))
    except (ServiceConfigError, OSError, httpx2.HTTPError, ValueError) as error:
        code = error.code if isinstance(error, ServiceConfigError) else "connector_configuration_or_connection_failed"
        print(json.dumps({"error": {"code": code}}))
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        return
