"""Private, bounded standard tracing and low-cardinality in-memory metrics.

No provider, exporter or worker exists until traces are explicitly enabled in
the final worker's lifespan. Export failures are observation failures only.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from time import perf_counter
from typing import Any, ParamSpec, TypeVar, cast
from uuid import UUID, uuid4

from lingshu_gate import __version__
from lingshu_gate.telemetry_config import TelemetryConfig

P = ParamSpec("P")
R = TypeVar("R")
logger = logging.getLogger(__name__)
OUTCOMES = frozenset({"success", "denied", "invalid", "timeout", "error", "aborted"})
ENTRIES = frozenset({"rest", "mcp", "catalog", "group", "pin", "internal"})
TRANSPORTS = frozenset({"builtin", "stdio", "streamable_http", "unknown"})
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
PHASES = frozenset({"request", "invoke", "authorization", "quota", "prepare", "queue", "downstream", "retry"})
BUCKETS = (0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0)
CAPACITY = 1024
BATCH_SIZE = 64

_current: ContextVar[TelemetryService | None] = ContextVar("gate_telemetry", default=None)
_correlation: ContextVar[str | None] = ContextVar("gate_correlation", default=None)
_entry: ContextVar[str] = ContextVar("gate_entry", default="internal")
_request_result: ContextVar[dict[str, str] | None] = ContextVar("gate_request_result", default=None)
_execution: ContextVar[SpanObservation | None] = ContextVar("gate_execution", default=None)
_invocation: ContextVar[SpanObservation | None] = ContextVar("gate_invocation", default=None)
_export_http: ContextVar[bool] = ContextVar("gate_export_http", default=False)


class _ExportHttpLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # urllib3 can log remote malformed headers before requests returns.
        # This affects only this exporter request's context, not business HTTP.
        return not _export_http.get()


_export_log_filter = _ExportHttpLogFilter()



def valid_correlation(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"[0-9a-fA-F]{32}", value):
        return value.lower()
    if len(value) == 36:
        try:
            parsed = str(UUID(value))
            return parsed if value.lower() == parsed else None
        except ValueError:
            pass
    return None


def correlation_id(value: str | None = None) -> str:
    return valid_correlation(value) or _correlation.get() or str(uuid4())


def exception_outcome(error: BaseException) -> str:
    from urllib.error import URLError

    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, TimeoutError) or getattr(current, "code", None) == "catalog_validation_timeout":
            return "timeout"
        if type(current).__name__ in {"AccessDeniedError", "ArgumentPolicyDenied", "UserCredentialBindingError"}:
            return "denied"
        code = getattr(current, "code", "")
        status = getattr(current, "status_code", None)
        if status in {401, 403} or code in {"argument_policy_denied", "tool_authorization_changed", "catalog_identity_changed", "catalog_tool_unavailable"}:
            return "denied"
        if type(current).__name__ in {"ValidationError", "ToolNotFoundError"} or status in {400, 404, 409, 422} or code in {
            "tool_arguments_invalid", "catalog_arguments_invalid", "catalog_schema_revision_conflict",
            "catalog_target_unavailable", "group_tool_contract_changed",
        }:
            return "invalid"
        current = current.reason if isinstance(current, URLError) and isinstance(current.reason, BaseException) else current.__cause__ or current.__context__
    return "aborted" if not isinstance(error, Exception) else "error"


def remember_failure(error: BaseException) -> None:
    # Call only when the business boundary has selected its final failure;
    # a recovered first attempt must not taint a successful logical invocation.
    outcome = exception_outcome(error)
    for observed in (_invocation.get(), _execution.get()):
        if observed is not None:
            observed.outcome = outcome


def response_outcome(result: Any) -> str:
    if hasattr(result, "ok") and not result.ok:
        output = result.output if isinstance(result.output, dict) else {}
        error = output.get("error", {})
        code = error.get("code") if isinstance(error, dict) else None
        if code in {"argument_policy_denied", "tool_authorization_changed", "catalog_identity_changed", "catalog_tool_unavailable"}:
            return "denied"
        if code in {"tool_arguments_invalid", "catalog_arguments_invalid", "catalog_schema_revision_conflict", "group_tool_contract_changed"}:
            return "invalid"
        return "error"
    output = result.output if hasattr(result, "output") else result
    return "error" if isinstance(output, dict) and output.get("isError") is True else "success"


@dataclass
class SpanObservation:
    outcome: str = "success"
    attributes: dict[str, Any] = field(default_factory=dict)
    dispatched: bool = False
    dispatch_time: float = 0.0


@dataclass
class _Metric:
    count: int = 0
    total: float = 0.0
    buckets: list[int] = field(default_factory=lambda: [0] * len(BUCKETS))


class _ExportState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.pending = 0
        self.inflight = 0
        self.accepted = 0
        self.failed = 0
        self.dropped_full = 0
        self.dropped_closed = 0
        self.closed = False
        self.shutdown_timed_out = False
        self.last_failure_code: str | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {"pending": self.pending, "inflight": self.inflight, "export_accepted_spans": self.accepted,
                    "failed_spans": self.failed, "dropped_queue_full": self.dropped_full,
                    "dropped_closed": self.dropped_closed, "closed": self.closed,
                    "shutdown_timed_out": self.shutdown_timed_out, "last_failure_code": self.last_failure_code}


def _standard_provider(config: TelemetryConfig, state: _ExportState) -> tuple[Any, Any, Any, Any, Any]:
    # Deliberately lazy: default-off startup does not import the SDK or start it.
    import requests
    from opentelemetry.context import Context
    from opentelemetry.exporter.otlp.proto.http import Compression
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.metrics import NoOpMeterProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan, SpanLimits, SpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    from lingshu_gate.service_io import secret_file

    fixed_headers = {"Content-Type": "application/x-protobuf", "User-Agent": "lingshu-gate-otel/" + __version__}
    if config.otlp_token_file:
        fixed_headers["Authorization"] = "Bearer " + secret_file(config.otlp_token_file)
    verify: bool | str = str(config.otlp_ca_file) if config.otlp_ca_file else True
    owner_pid = os.getpid()
    for name in ("urllib3.connection", "urllib3.connectionpool", "urllib3.poolmanager", "urllib3.response", "urllib3.util.retry"):
        logging.getLogger(name).addFilter(_export_log_filter)

    class RestrictedSession(requests.Session):
        def __init__(self) -> None:
            super().__init__()
            self.trust_env = False
            self._closed = threading.Event()
            self.headers.clear()
            self.headers.update(fixed_headers)

        def resolve_redirects(self, *args: Any, **kwargs: Any) -> Generator[Any, None, None]:
            # requests otherwise prepares response.next and consumes a 3xx body
            # even with allow_redirects=False.
            yield from ()

        def close(self) -> None:
            self._closed.set()
            super().close()

        def post(self, url: Any, data: Any = None, json: Any = None, **kwargs: Any) -> Any:
            token = _export_http.set(True)
            try:
                return self._post(url, data, **kwargs)
            finally:
                _export_http.reset(token)

        def _post(self, url: Any, data: Any = None, **kwargs: Any) -> Any:
            if url != config.otlp_endpoint:
                raise requests.RequestException("otlp_endpoint_mismatch") from None
            self.cookies.clear()
            self.headers.clear()
            self.headers.update(fixed_headers)
            try:
                timeout = max(0.001, min(float(kwargs.get("timeout", 2.0)), 2.0))
                if state.closed or self._closed.is_set() or os.getpid() != owner_pid:
                    raise requests.RequestException("otlp_export_closed")
                response = super().post(config.otlp_endpoint, data=data, timeout=timeout, verify=verify, cert=None,
                    proxies={}, stream=True, allow_redirects=False)
                try:
                    status = response.status_code
                finally:
                    response.close()
                # Do not forward collector text, redirects, cookies, request
                # objects or retryable statuses into SDK error logging.
                sanitized = requests.Response()
                sanitized.status_code = status if 200 <= status < 300 else 400
                sanitized.reason = "otlp_http_rejected" if sanitized.status_code == 400 else "accepted"
                sanitized._content = b""
                return sanitized
            except requests.RequestException:
                raise requests.RequestException("otlp_transport_failed") from None
            finally:
                self.cookies.clear()

    noop_meter = NoOpMeterProvider()
    exporter = OTLPSpanExporter(endpoint=config.otlp_endpoint, headers=dict(fixed_headers), timeout=2.0,
        compression=Compression.NoCompression, session=RestrictedSession(), meter_provider=noop_meter,
        certificate_file=str(config.otlp_ca_file) if config.otlp_ca_file else None)
    exporter_closed = threading.Event()

    class CountedExporter(SpanExporter):
        def export(self, spans: Sequence[ReadableSpan]) -> Any:
            count = len(spans)
            with state.lock:
                state.pending -= count
                state.inflight += count
                closed = state.closed or os.getpid() != owner_pid
            result = SpanExportResult.FAILURE
            try:
                if not closed:
                    result = exporter.export(spans)
            except Exception:
                # Keep arbitrary SDK/transport exceptions out of BSP tracebacks.
                result = SpanExportResult.FAILURE
            finally:
                with state.lock:
                    state.inflight -= count
                    if result == SpanExportResult.SUCCESS:
                        state.accepted += count
                    else:
                        state.failed += count
                        state.last_failure_code = "export_closed" if closed else "export_failed"
            return result

        def shutdown(self) -> None:
            if not exporter_closed.is_set():
                exporter_closed.set()
                exporter.shutdown()

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    provider = TracerProvider(resource=Resource({"service.name": "lingshu-gate", "service.version": __version__}),
        sampler=TraceIdRatioBased(config.sample_ratio), shutdown_on_exit=False, meter_provider=noop_meter,
        span_limits=SpanLimits(max_attributes=12, max_span_attributes=12, max_attribute_length=128,
            max_span_attribute_length=128, max_events=0, max_links=0, max_event_attributes=0, max_link_attributes=0))
    counted = CountedExporter()
    try:
        batch = BatchSpanProcessor(counted, max_queue_size=CAPACITY, max_export_batch_size=BATCH_SIZE,
            schedule_delay_millis=1000, export_timeout_millis=2000, meter_provider=noop_meter)
    except Exception:
        counted.shutdown()
        provider.shutdown()
        raise


    class BoundedProcessor(SpanProcessor):
        def on_end(self, span: ReadableSpan) -> None:
            if not span.context or not span.context.trace_flags.sampled or os.getpid() != owner_pid:
                return
            # Only scalar accounting and enqueue run under this short lock.
            # Export, shutdown joins and all collector I/O happen outside it.
            with state.lock:
                if state.closed:
                    state.dropped_closed += 1
                elif state.pending + state.inflight >= CAPACITY:
                    state.dropped_full += 1
                else:
                    state.pending += 1
                    try:
                        batch.on_end(span)
                    except Exception:
                        state.pending -= 1
                        state.failed += 1
                        state.last_failure_code = "enqueue_failed"

        def shutdown(self) -> None:
            batch.shutdown()

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            # Application shutdown deliberately never invokes a blocking flush.
            return False


    provider.add_span_processor(BoundedProcessor())
    return provider, provider.get_tracer("lingshu_gate", __version__), counted, TraceContextTextMapPropagator(), Context


class TelemetryService:
    def __init__(self, config: TelemetryConfig) -> None:
        self.config = config
        self.export = _ExportState()
        self._provider: Any = None
        self._tracer: Any = None
        self._exporter: Any = None
        self._propagator: Any = None
        self._context_factory: Any = None
        self._pid = os.getpid()
        self._metrics_lock = threading.Lock()
        self._metrics: dict[tuple[str, tuple[tuple[str, str], ...]], _Metric] = {}
        self.allowed_routes: frozenset[str] = frozenset()
        self.started = False
        self.stopped = False

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        self._pid = os.getpid()
        if not self.config.traces_enabled:
            return
        if os.environ.get("OTEL_SDK_DISABLED", "").lower().strip() == "true":
            self.export.last_failure_code = "sdk_environment_disabled"
            return
        try:
            self._provider, self._tracer, self._exporter, self._propagator, self._context_factory = _standard_provider(self.config, self.export)
        except Exception:
            self.export.last_failure_code = "initialization_failed"
            logger.warning("Gate trace export could not initialize; business service continues")

    def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        with self.export.lock:
            self.export.closed = True
        if self._provider is None:
            return
        def shutdown() -> None:
            try:
                # Stop new HTTP work and wake SDK retry waits before joining BSP.
                self._exporter.shutdown()
                self._provider.shutdown()
            except Exception:
                with self.export.lock:
                    self.export.last_failure_code = "shutdown_failed"
        try:
            worker = threading.Thread(target=shutdown, name="gate-telemetry-shutdown", daemon=True)
            worker.start()
            worker.join(1.0)
            if worker.is_alive():
                with self.export.lock:
                    self.export.shutdown_timed_out = True
        except Exception:
            self.export.last_failure_code = "shutdown_failed"

    def status(self) -> dict[str, Any]:
        return {"metrics_enabled": self.config.metrics_enabled, "traces_enabled": self.config.traces_enabled,
                "traces_ready": self._tracer is not None and not self.export.closed,
                "queue_capacity": CAPACITY, "batch_size": BATCH_SIZE, **self.export.snapshot()}

    def safe_route(self, value: str) -> str:
        return value if value in self.allowed_routes else "unmatched"

    @contextmanager
    def activate(self, correlation: str, entry: str = "internal", request_result: dict[str, str] | None = None) -> Iterator[None]:
        service_token = _current.set(self)
        correlation_token = _correlation.set(correlation)
        entry_token = _entry.set(entry if entry in ENTRIES else "internal")
        result_token = _request_result.set(request_result)
        try:
            yield
        finally:
            _request_result.reset(result_token)
            _entry.reset(entry_token)
            _correlation.reset(correlation_token)
            _current.reset(service_token)

    def parent_context(self, headers: list[tuple[bytes, bytes]]) -> Any:
        if self._propagator is None:
            return None
        values = [value for name, value in headers if name.lower() == b"traceparent"]
        carrier: dict[str, str] = {}
        if len(values) == 1 and len(values[0]) <= 256:
            try:
                carrier["traceparent"] = values[0].decode("ascii")
            except UnicodeError:
                pass
        try:
            return self._propagator.extract(carrier, context=self._context_factory())
        except Exception:
            self.export.last_failure_code = "propagation_failed"
            return None

    @contextmanager
    def span(self, name: str, *, context: Any = None, attributes: dict[str, Any] | None = None) -> Iterator[SpanObservation]:
        observed = SpanObservation(attributes=dict(attributes or {}))
        manager: Any = None
        span: Any = None
        if name in PHASES and self._tracer is not None and not self.export.closed and os.getpid() == self._pid:
            try:
                manager = self._tracer.start_as_current_span("gate." + name, context=context,
                    record_exception=False, set_status_on_exception=False)
                span = manager.__enter__()
            except Exception:
                manager = None
                self.export.last_failure_code = "span_failed"
        try:
            yield observed
        except BaseException as error:
            observed.outcome = exception_outcome(error)
            raise
        finally:
            if span is not None:
                try:
                    from opentelemetry.trace import StatusCode
                    attributes = {**observed.attributes, "gate.outcome": observed.outcome}
                    for key, value in attributes.items():
                        if self._safe_attribute(key, value):
                            span.set_attribute(key, value)
                    if observed.outcome != "success":
                        span.set_status(StatusCode.ERROR)
                except Exception:
                    self.export.last_failure_code = "span_failed"
            if manager is not None:
                try:
                    # Never let SDK's exception path format a business exception.
                    manager.__exit__(None, None, None)
                except Exception:
                    self.export.last_failure_code = "span_failed"

    def _safe_attribute(self, key: str, value: Any) -> bool:
        if key == "gate.entry":
            return value in ENTRIES
        if key == "gate.transport":
            return value in TRANSPORTS
        if key == "gate.outcome":
            return value in OUTCOMES
        if key == "gate.attempt":
            return value in {"initial", "retry"}
        if key == "gate.dispatched":
            return type(value) is bool
        if key == "http.request.method":
            return value in METHODS or value == "other"
        if key == "http.response.status_code":
            return type(value) is int and 100 <= value <= 599
        if key == "http.route":
            return value in self.allowed_routes or value == "unmatched"
        if key == "gate.correlation_id":
            return valid_correlation(value) is not None
        return False

    def record(self, name: str, labels: dict[str, str], duration: float) -> None:
        try:
            self._record(name, labels, duration)
        except Exception:
            self.export.last_failure_code = "aggregation_failed"

    def _record(self, name: str, labels: dict[str, str], duration: float) -> None:
        if not self.config.metrics_enabled:
            return
        label_attributes = {"entry": "gate.entry", "transport": "gate.transport", "outcome": "gate.outcome",
                            "attempt": "gate.attempt", "route": "http.route", "method": "http.request.method"}
        expected = {"http": {"route", "method", "outcome"}, "tool": {"entry", "transport", "outcome"},
                    "execution": {"transport", "attempt", "outcome"}}
        if name not in expected or set(labels) != expected[name]:
            return
        if not all(self._safe_attribute(label_attributes[key], value) for key, value in labels.items()):
            return
        key = (name, tuple(sorted(labels.items())))
        with self._metrics_lock:
            if key not in self._metrics and len(self._metrics) >= 4096:
                key = (name, (("overflow", "true"),))
            metric = self._metrics.setdefault(key, _Metric())
            metric.count += 1
            metric.total += max(0.0, duration)
            for index, bound in enumerate(BUCKETS):
                if duration <= bound:
                    metric.buckets[index] += 1

    def prometheus_text(self) -> str:
        with self._metrics_lock:
            metrics = [(name, labels, value.count, value.total, tuple(value.buckets))
                       for (name, labels), value in self._metrics.items()]
        def quoted(value: str) -> str:
            return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
        def tags(values: tuple[tuple[str, str], ...]) -> str:
            return "{" + ",".join(key + "=" + quoted(value) for key, value in values) + "}" if values else ""
        lines: list[str] = []
        for kind in ("http", "tool", "execution"):
            base = "gate_" + kind
            lines.extend(("# HELP " + base + "_total Process-local completed observations.",
                          "# TYPE " + base + "_total counter",
                          "# HELP " + base + "_duration_seconds Observation duration in seconds.",
                          "# TYPE " + base + "_duration_seconds histogram"))
            for name, labels, count, total, buckets in sorted(metrics):
                if name != kind:
                    continue
                lines.append(base + "_total" + tags(labels) + " " + str(count))
                for bound, count_in_bucket in zip(BUCKETS, buckets, strict=True):
                    lines.append(base + "_duration_seconds_bucket" + tags((*labels, ("le", str(bound)))) + " " + str(count_in_bucket))
                lines.append(base + "_duration_seconds_bucket" + tags((*labels, ("le", "+Inf"))) + " " + str(count))
                lines.append(base + "_duration_seconds_count" + tags(labels) + " " + str(count))
                lines.append(base + "_duration_seconds_sum" + tags(labels) + " " + format(total, ".12g"))
        status = self.status()
        for key in ("traces_ready", "pending", "inflight", "shutdown_timed_out"):
            metric_name = "gate_telemetry_" + key
            lines.extend(("# TYPE " + metric_name + " gauge", metric_name + " " + str(int(status[key]))))
        lines.append("# TYPE gate_telemetry_spans_total counter")
        for key in ("export_accepted_spans", "failed_spans", "dropped_queue_full", "dropped_closed"):
            lines.append('gate_telemetry_spans_total{outcome="' + key + '"} ' + str(status[key]))
        return "\n".join(lines) + "\n"


@contextmanager
def phase(name: str) -> Iterator[SpanObservation]:
    service = _current.get()
    if service is None:
        yield SpanObservation()
    else:
        with service.span(name) as observed:
            yield observed


@contextmanager
def queue_lock(lock: Any) -> Iterator[None]:
    with phase("queue"):
        lock.acquire()
    try:
        yield
    finally:
        lock.release()


@contextmanager
def invocation_entry(entry: str) -> Iterator[None]:
    selected = "pin" if entry == "group" and _entry.get() == "pin" else entry
    token = _entry.set(selected if selected in ENTRIES else "internal")
    try:
        yield
    finally:
        _entry.reset(token)


def _transport(definition: Any) -> str:
    if definition.source == "builtin":
        return "builtin"
    value = definition.metadata.get("transport_type")
    return value if value in TRANSPORTS else "unknown"


def _merge_outcome(outcome: str) -> None:
    result = _request_result.get()
    if result is not None and outcome != "success":
        result["outcome"] = outcome


def protocol_outcome(outcome: str) -> None:
    result = _request_result.get()
    if result is not None and result["outcome"] == "success" and outcome in OUTCOMES:
        result["outcome"] = outcome


def observed_invocation(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        service = _current.get()
        if service is None:
            return function(*args, **kwargs)
        transport = "unknown"
        try:
            registry = args[1] if len(args) > 1 else kwargs["registry"]
            tool_id = args[3] if len(args) > 3 else kwargs["tool_id"]
            transport = _transport(cast(Any, registry).get_definition(tool_id))
        except Exception:
            pass
        entry = _entry.get()
        started = perf_counter()
        with service.span("invoke", attributes={"gate.entry": entry, "gate.transport": transport}) as observed:
            token = _invocation.set(observed)
            try:
                result = function(*args, **kwargs)
                if observed.outcome == "success":
                    observed.outcome = response_outcome(result)
                return result
            except BaseException as error:
                observed.outcome = exception_outcome(error)
                raise
            finally:
                _invocation.reset(token)
                _merge_outcome(observed.outcome)
                service.record("tool", {"entry": entry, "transport": transport, "outcome": observed.outcome}, perf_counter() - started)
    return wrapped


@contextmanager
def execution(transport: str, *, retry: bool = False) -> Iterator[SpanObservation]:
    service = _current.get()
    transport = transport if transport in TRANSPORTS else "unknown"
    if service is None:
        yield SpanObservation()
        return
    with service.span("downstream", attributes={"gate.transport": transport, "gate.attempt": "retry" if retry else "initial"}) as observed:
        token = _execution.set(observed)
        try:
            yield observed
        except BaseException as error:
            observed.outcome = exception_outcome(error)
            raise
        finally:
            _execution.reset(token)
            observed.attributes["gate.dispatched"] = observed.dispatched
            if observed.dispatched:
                service.record("execution", {"transport": transport, "attempt": "retry" if retry else "initial", "outcome": observed.outcome},
                               perf_counter() - observed.dispatch_time)


def mark_execution_started() -> None:
    # Local bookkeeping only: no SDK call, queue or shared lock after final guard.
    observed = _execution.get()
    if observed is not None:
        observed.dispatched = True
        observed.dispatch_time = perf_counter()


def observed_builtin(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            registry = args[0]
            tool_id = args[1] if len(args) > 1 else kwargs["tool_id"]
            builtin = cast(Any, registry).get_definition(tool_id).source == "builtin"
        except Exception:
            builtin = False
        if _current.get() is None or not builtin:
            return function(*args, **kwargs)
        with execution("builtin") as observed:
            result = function(*args, **kwargs)
            if observed.outcome == "success":
                observed.outcome = response_outcome(result)
            return result
    return wrapped


def trace_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    correlation = _correlation.get()
    if correlation:
        headers["X-Correlation-ID"] = correlation
    service = _current.get()
    if service is not None and service._propagator is not None and not service.export.closed:
        try:
            carrier: dict[str, str] = {}
            service._propagator.inject(carrier)
            if "traceparent" in carrier:
                headers["traceparent"] = carrier["traceparent"]
        except Exception:
            service.export.last_failure_code = "propagation_failed"
    return headers
