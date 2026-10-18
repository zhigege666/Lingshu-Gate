"""Bounded configuration and wire contracts for the explicit HTTP connector."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lingshu_gate.service_io import ServiceConfigError, bounded, canonical, digest, fixed_url, loopback, secret_file, unique_pairs

REQUEST_BYTES = 1024 * 1024
RESPONSE_BYTES = 8 * 1024 * 1024
FRAME_BYTES = 12 * 1024 * 1024
IN_FLIGHT = 16
SESSION_TTL = 3600
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
Revision = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
RequestId = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
ErrorCode = Literal["connector_upstream_http_error", "connector_upstream_timeout_result_unknown",
    "connector_upstream_redirect_rejected", "connector_response_invalid", "connector_request_rejected",
    "connector_upstream_unavailable_result_unknown"]
REQUEST_HEADERS = frozenset({"content-type", "accept", "mcp-protocol-version", "mcp-method", "mcp-name", "mcp-session-id"})
RESPONSE_HEADERS = frozenset({"content-type", "mcp-protocol-version", "mcp-session-id"})
METHODS = frozenset({"server/discover", "initialize", "notifications/initialized", "ping", "tools/list", "tools/call"})
_SSE_LINE_END = re.compile(b"[\r\n]")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ConnectorIdentity(StrictModel):
    id: Identifier
    token_file: str = Field(min_length=1, max_length=4096)
    targets: list[Identifier] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("duplicate_target")
        return self


class RelayConfig(StrictModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    host: str = "127.0.0.1"
    port: int = Field(default=18882, ge=1, le=65535)
    allowed_hosts: list[str] = Field(default_factory=list, max_length=32)
    allowed_origins: list[str] = Field(default_factory=list, max_length=32)
    tls_cert_file: str | None = None
    tls_key_file: str | None = None
    agents: list[ConnectorIdentity] = Field(min_length=1, max_length=32)
    consumers: list[ConnectorIdentity] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def trust(self):
        if bool(self.tls_cert_file) != bool(self.tls_key_file):
            raise ValueError("tls_certificate_and_key_required")
        if not loopback(self.host) and not (self.tls_cert_file and self.allowed_hosts):
            raise ValueError("remote_listener_requires_tls_and_allowed_host")
        if not self.allowed_hosts:
            self.allowed_hosts = [f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"]
        if any(not host or host != host.lower() or len(host) > 256 or "*" in host or "/" in host
               or any(ord(c) < 33 or ord(c) == 127 for c in host) for host in self.allowed_hosts):
            raise ValueError("allowed_host_invalid")
        for origin in self.allowed_origins:
            if fixed_url(origin) != origin or "/" in origin.split("://", 1)[1]:
                raise ValueError("allowed_origin_invalid")
        agents, consumers = [i.id for i in self.agents], [i.id for i in self.consumers]
        if len(set(agents)) != len(agents) or len(set(consumers)) != len(consumers):
            raise ValueError("duplicate_identity")
        targets = [target for identity in self.agents for target in identity.targets]
        if len(targets) > 64 or len(set(targets)) != len(targets):
            raise ValueError("target_requires_one_agent_owner")
        if any(not set(identity.targets).issubset(targets) for identity in self.consumers):
            raise ValueError("consumer_target_unknown")
        return self


class AgentTarget(StrictModel):
    id: Identifier
    url: str = Field(max_length=2048)
    allow_private_http: bool = False
    token_file: str | None = Field(default=None, max_length=4096)
    ca_file: str | None = Field(default=None, max_length=4096)
    timeout_seconds: int = Field(default=30, ge=1, le=60)

    @model_validator(mode="after")
    def target(self):
        self.url = fixed_url(self.url, private_http=self.allow_private_http)
        return self

    @property
    def revision(self) -> str:
        return digest(self.model_dump())


class AgentConfig(StrictModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    agent_id: Identifier
    relay_url: str = Field(max_length=2048)
    token_file: str = Field(min_length=1, max_length=4096)
    ca_file: str | None = Field(default=None, max_length=4096)
    targets: list[AgentTarget] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def trust(self):
        self.relay_url = fixed_url(self.relay_url, websocket=True)
        if not self.relay_url.endswith("/connector/agent") or len({t.id for t in self.targets}) != len(self.targets):
            raise ValueError("agent_configuration_invalid")
        return self


class Hello(StrictModel):
    version: int = Field(default=1, ge=1, le=1)
    kind: Literal["hello"] = "hello"
    targets: dict[Identifier, Revision] = Field(min_length=1, max_length=64)


class HelloAck(StrictModel):
    version: int = Field(default=1, ge=1, le=1)
    kind: Literal["ready"] = "ready"
    generation: RequestId


class RelayRequest(StrictModel):
    version: int = Field(default=1, ge=1, le=1)
    kind: Literal["request"] = "request"
    request_id: RequestId
    target_id: Identifier
    revision: Revision
    method: Literal["POST", "DELETE"]
    timeout_ms: int = Field(ge=1, le=60000)
    expires_at_ms: int = Field(ge=1, le=9007199254740991)
    headers: dict[str, str] = Field(max_length=6)
    body: str = Field(max_length=(REQUEST_BYTES + 2) // 3 * 4)


class RelayResponse(StrictModel):
    version: int = Field(default=1, ge=1, le=1)
    kind: Literal["response"] = "response"
    request_id: RequestId
    status: int = Field(ge=200, le=599)
    headers: dict[str, str] = Field(max_length=3)
    body: str = Field(max_length=(RESPONSE_BYTES + 2) // 3 * 4)
    outcome: Literal["completed", "not_forwarded", "unknown"] = "completed"
    error_code: ErrorCode | None = None


Model = TypeVar("Model", bound=BaseModel)


def parse_model(model: type[Model], value: Any) -> Model:
    try:
        return model.model_validate(value)
    except (ValidationError, ValueError, TypeError):
        raise ServiceConfigError("connector_configuration_or_frame_invalid") from None


def parse_frame(raw: str | bytes, model: type[Model], *, limit: int = FRAME_BYTES) -> Model:
    try:
        if len(raw) > limit or len(raw.encode() if isinstance(raw, str) else raw) > limit:
            raise ServiceConfigError("connector_frame_size_limit")
        value = json.loads(raw, object_pairs_hook=unique_pairs)
        bounded(value, max_nodes=512, max_depth=8)
        return parse_model(model, value)
    except ServiceConfigError:
        raise
    except (ValueError, UnicodeError, RecursionError, TypeError):
        raise ServiceConfigError("connector_frame_invalid") from None


def encode_body(body: bytes) -> str:
    return base64.b64encode(body).decode("ascii")


def decode_body(value: str, limit: int) -> bytes:
    try:
        if len(value) > (limit + 2) // 3 * 4:
            raise ValueError
        raw = base64.b64decode(value, validate=True)
        if len(raw) > limit:
            raise ValueError
        return raw
    except (ValueError, binascii.Error):
        raise ServiceConfigError("connector_body_size_or_encoding_invalid") from None


def filtered_headers(pairs: list[tuple[str, str]], *, response: bool = False) -> dict[str, str]:
    allowed = RESPONSE_HEADERS if response else REQUEST_HEADERS
    result: dict[str, str] = {}
    for key, value in pairs:
        name = key.lower()
        if name not in allowed:
            continue
        if name in result or len(value) > 4096 or not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ServiceConfigError("connector_header_invalid")
        result[name] = value
    if sum(len(k) + len(v) for k, v in result.items()) > 8192:
        raise ServiceConfigError("connector_header_size_limit")
    return result


def request_rpc(body: bytes) -> dict[str, Any]:
    try:
        if len(body) > REQUEST_BYTES:
            raise ValueError
        value = json.loads(body, object_pairs_hook=unique_pairs)
        bounded(value, max_nodes=50000)
        if (not isinstance(value, dict) or value.get("jsonrpc") != "2.0" or value.get("method") not in METHODS
                or "id" in value and (type(value["id"]) not in {str, int} or len(str(value["id"])) > 256)):
            raise ValueError
        if value["method"] == "notifications/initialized" and "id" in value:
            raise ValueError
        if value["method"] != "notifications/initialized" and "id" not in value:
            raise ValueError
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ServiceConfigError("connector_mcp_request_unsupported") from None


def response_matches(value: Any, request_id: Any) -> bool:
    return (isinstance(value, dict) and value.get("jsonrpc") == "2.0" and "method" not in value
            and type(value.get("id")) is type(request_id) and value.get("id") == request_id
            and ("result" in value) != ("error" in value))


class SseReply:
    """Find one matching response without waiting for an upstream stream EOF."""
    def __init__(self, request_id: str | int):
        self.request_id = request_id
        self.buffer = bytearray()
        self.data: list[str] = []
        self.total = 0
        self.events = 0
        self.skip_lf = False
        self.first_line = True
        self.scan_offset = 0

    def feed(self, chunk: bytes) -> bytes | None:
        self.total += len(chunk)
        if self.total > RESPONSE_BYTES:
            raise ServiceConfigError("connector_response_size_limit")
        self.buffer.extend(chunk)
        while True:
            if self.skip_lf and self.buffer:
                if self.buffer[0] == 10:
                    del self.buffer[:1]
                self.skip_lf = False
            match = _SSE_LINE_END.search(self.buffer, self.scan_offset)
            if match is None:
                self.scan_offset = len(self.buffer)
                return None
            line = bytes(self.buffer[:match.start()])
            self.skip_lf = match.group() == b"\r"
            del self.buffer[:match.end()]
            self.scan_offset = 0
            text = line.decode("utf-8")
            if self.first_line:
                text = text.removeprefix("\ufeff")
                self.first_line = False
            if not text:
                self.events += 1
                if self.events > 4096:
                    raise ServiceConfigError("connector_sse_event_limit")
                if self.data:
                    raw = "\n".join(self.data).encode()
                    self.data.clear()
                    value = json.loads(raw, object_pairs_hook=unique_pairs)
                    bounded(value, max_nodes=100000)
                    if response_matches(value, self.request_id):
                        return raw
            elif text.startswith("data:"):
                self.data.append(text[6:] if text.startswith("data: ") else text[5:])


def credential_hash(path: str) -> str:
    value = secret_file(Path(path))
    if len(value) < 32:
        raise ServiceConfigError("connector_credential_minimum_32_characters")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def failure_response(request_id: str, code: str, *, forwarded: bool) -> RelayResponse:
    error_code: ErrorCode = "connector_response_invalid" if forwarded else "connector_request_rejected"
    if code == "connector_upstream_timeout_result_unknown":
        error_code = "connector_upstream_timeout_result_unknown"
    elif code == "connector_upstream_unavailable_result_unknown":
        error_code = "connector_upstream_unavailable_result_unknown"
    elif code == "connector_upstream_redirect_rejected":
        error_code = "connector_upstream_redirect_rejected"
    return RelayResponse(request_id=request_id, status=502 if forwarded else 503, headers={"content-type": "application/json"},
        body=encode_body(canonical({"code": code, "execution": "unknown" if forwarded else "not_forwarded"})),
        outcome="unknown" if forwarded else "not_forwarded", error_code=error_code)
