"""Explicit first-party normalization; never infer defaults for remote tools."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from lingshu_gate.domain.tool_structure import copy_bounded_json

ArgumentPreparer = Callable[[dict[str, Any]], dict[str, Any]]


def owned_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    from lingshu_gate.registry import ToolDispatchRejectedError

    try:
        if not isinstance(arguments, dict):
            raise ValueError
        return copy_bounded_json(arguments, max_bytes=1_048_576, max_nodes=8192, max_depth=32)
    except (ValueError, TypeError, RecursionError, RuntimeError, OverflowError):
        raise ToolDispatchRejectedError("tool_arguments_invalid", "Tool arguments must be a bounded finite JSON object.") from None


def model_preparer(model: type[BaseModel], *,
                   transform: Callable[[BaseModel, dict[str, Any]], None] | None = None) -> ArgumentPreparer:
    def prepare(arguments: dict[str, Any]) -> dict[str, Any]:
        from lingshu_gate.registry import ToolDispatchRejectedError

        try:
            parsed = model.model_validate(arguments)
            effective = parsed.model_dump(mode="json")
            if transform is not None:
                transform(parsed, effective)
            return effective
        except (ValueError, TypeError, RecursionError, OverflowError):
            # Pydantic's default error string includes input values.
            raise ToolDispatchRejectedError("tool_arguments_invalid", "Check the tool's declared input fields and types.") from None
    return prepare
