"""Request-only context propagation; no raw URLs, headers or bodies are observed."""
from __future__ import annotations

from time import perf_counter
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from lingshu_gate.telemetry import METHODS, TelemetryService, correlation_id, exception_outcome, valid_correlation


def _correlation(scope: Scope) -> str:
    state = scope.setdefault("state", {})
    cached = valid_correlation(state.get("gate_correlation_id"))
    if cached:
        return cached
    values = [value for name, value in scope.get("headers", ()) if name.lower() == b"x-correlation-id"]
    value = None
    if len(values) == 1 and len(values[0]) <= 36:
        try:
            value = values[0].decode("ascii")
        except UnicodeError:
            pass
    selected = correlation_id(value)
    state["gate_correlation_id"] = selected
    return selected


def request_correlation(request: Request) -> str:
    return _correlation(request.scope)


class TelemetryMiddleware:
    def __init__(self, app: ASGIApp, *, service: TelemetryService, routes: list[Any]) -> None:
        self.app = app
        self.service = service
        # Only application-owned templates become labels, never a request path.
        service.allowed_routes = frozenset(route.path for route in routes if isinstance(getattr(route, "path", None), str))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        correlation = _correlation(scope)
        path = scope.get("path", "")
        entry = "mcp" if path in {"/mcp", "/mcp/manage"} else "catalog" if path.startswith("/v1/catalog/") else "rest"
        method = scope.get("method", "other")
        method = method if method in METHODS else "other"
        status_code = 500
        result = {"outcome": "success"}
        started = perf_counter()

        async def send_observed(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message = {**message, "headers": [(name, value) for name, value in message.get("headers", ())
                    if name.lower() != b"x-correlation-id"] + [(b"x-correlation-id", correlation.encode("ascii"))]}
            await send(message)

        with self.service.activate(correlation, entry, result):
            with self.service.span("request", context=self.service.parent_context(scope.get("headers", [])),
                                   attributes={"gate.correlation_id": correlation, "http.request.method": method}) as observed:
                try:
                    await self.app(scope, receive, send_observed)
                    observed.outcome = (result["outcome"] if result["outcome"] != "success"
                        else "denied" if status_code in {401, 403}
                        else "timeout" if status_code in {408, 504}
                        else "invalid" if status_code in {400, 404, 405, 409, 422}
                        else "error" if status_code >= 400 else "success")
                except BaseException as error:
                    observed.outcome = exception_outcome(error)
                    raise
                finally:
                    route = self.service.safe_route(getattr(scope.get("route"), "path", "unmatched"))
                    observed.attributes.update({"http.route": route, "http.response.status_code": status_code})
                    self.service.record("http", {"route": route, "method": method, "outcome": observed.outcome},
                                        perf_counter() - started)
