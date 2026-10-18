"""Explicit instance-owned telemetry configuration; no implicit OTEL destinations."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from lingshu_gate.service_io import fixed_url, unique_pairs


@dataclass(frozen=True)
class TelemetryConfig:
    metrics_enabled: bool = False
    traces_enabled: bool = False
    otlp_endpoint: str = ""
    otlp_token_file: Path | None = None
    otlp_ca_file: Path | None = None
    sample_ratio: float = 1.0

    def __post_init__(self) -> None:
        if type(self.metrics_enabled) is not bool or type(self.traces_enabled) is not bool:
            raise ValueError("telemetry_flags_invalid")
        if type(self.sample_ratio) not in {float, int} or not 0 <= self.sample_ratio <= 1 or not math.isfinite(self.sample_ratio):
            raise ValueError("telemetry_sample_ratio_invalid")
        if not isinstance(self.otlp_endpoint, str) or len(self.otlp_endpoint) > 2048:
            raise ValueError("telemetry_endpoint_invalid")
        if self.otlp_endpoint:
            normalized = fixed_url(self.otlp_endpoint)
            if not urlsplit(normalized).path:
                raise ValueError("telemetry_requires_complete_trace_endpoint")
            object.__setattr__(self, "otlp_endpoint", normalized)
        if self.traces_enabled and not self.otlp_endpoint:
            raise ValueError("telemetry_requires_complete_trace_endpoint")
        for value in (self.otlp_token_file, self.otlp_ca_file):
            if value is not None and (not isinstance(value, Path) or not value.is_absolute() or len(str(value)) > 1024
                                      or any(ord(c) < 32 for c in str(value))):
                raise ValueError("telemetry_file_path_invalid")

    @classmethod
    def parse(cls, text: str) -> TelemetryConfig:
        try:
            if len(text) > 8192:
                raise ValueError
            value = json.loads(text, object_pairs_hook=unique_pairs)
            if not isinstance(value, dict) or set(value) - set(cls.__dataclass_fields__):
                raise ValueError
            raw: dict[str, Any] = dict(value)
            for name in ("otlp_token_file", "otlp_ca_file"):
                if raw.get(name) is not None:
                    if not isinstance(raw[name], str) or not raw[name]:
                        raise ValueError
                    raw[name] = Path(raw[name])
            return cls(**raw)
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise ValueError("telemetry_configuration_invalid") from None
