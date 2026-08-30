"""Health probe application service."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from lingshu_gate.domain.health import ComponentStatus, ProbeReport
from lingshu_gate.ports.control_plane import (
    ConfigurationSource,
    RuntimeDriver,
    StateStore,
)


@dataclass(frozen=True)
class StartupSnapshot:
    phase: str
    detail: str

    @property
    def ready(self) -> bool:
        return self.phase == "ready"


class StartupState:
    """Thread-safe lifecycle state shared by startup and HTTP probe handlers."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._phase = "created"
        self._detail = "application lifespan has not started"

    def mark_starting(self) -> None:
        self._set("starting", "application startup is in progress")

    def mark_ready(self) -> None:
        self._set("ready", "application startup completed")

    def mark_failed(self, _error: BaseException) -> None:
        # Probe endpoints are intentionally unauthenticated. Keep exception details
        # in application logs and expose only the lifecycle phase here.
        self._set("failed", "application startup failed")

    def mark_stopping(self) -> None:
        self._set("stopping", "application shutdown is in progress")

    def snapshot(self) -> StartupSnapshot:
        with self._lock:
            return StartupSnapshot(phase=self._phase, detail=self._detail)

    def _set(self, phase: str, detail: str) -> None:
        with self._lock:
            self._phase = phase
            self._detail = detail


class HealthService:
    """Evaluate liveness, startup, and readiness without depending on FastAPI."""

    def __init__(
        self,
        *,
        service_name: str,
        version: str,
        startup_state: StartupState,
        state_store: StateStore,
        configuration_source: ConfigurationSource,
        runtime_driver: RuntimeDriver,
    ) -> None:
        self.service_name = service_name
        self.version = version
        self.startup_state = startup_state
        self.state_store = state_store
        self.configuration_source = configuration_source
        self.runtime_driver = runtime_driver

    def liveness(self) -> ProbeReport:
        return ProbeReport(
            status="ok",
            service=self.service_name,
            version=self.version,
            checks=(ComponentStatus("process", True, "HTTP process is responding"),),
        )

    def startup(self) -> ProbeReport:
        snapshot = self.startup_state.snapshot()
        check = ComponentStatus(
            "startup",
            snapshot.ready,
            snapshot.detail,
            {"phase": snapshot.phase},
        )
        return ProbeReport(
            status="ok" if check.ok else "starting",
            service=self.service_name,
            version=self.version,
            checks=(check,),
        )

    def readiness(self) -> ProbeReport:
        snapshot = self.startup_state.snapshot()
        checks = (
            ComponentStatus(
                "startup",
                snapshot.ready,
                snapshot.detail,
                {"phase": snapshot.phase},
            ),
            self._safe_check("database", self.state_store.readiness),
            self._safe_check("configuration", self.configuration_source.readiness),
            self._safe_check("runtime", self.runtime_driver.readiness),
        )
        ready = all(check.ok for check in checks)
        return ProbeReport(
            status="ok" if ready else "not_ready",
            service=self.service_name,
            version=self.version,
            checks=checks,
        )

    @staticmethod
    def _safe_check(
        name: str,
        check: Callable[[], ComponentStatus],
    ) -> ComponentStatus:
        try:
            return check()
        except Exception as exc:  # noqa: BLE001 - probes must report failure, not crash
            return ComponentStatus(
                name,
                False,
                "component probe failed",
                {"error_type": type(exc).__name__},
            )
