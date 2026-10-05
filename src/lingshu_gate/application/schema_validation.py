"""Finite schema expansion and killable local validation of untrusted contracts."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import unquote

from lingshu_gate.registry import ToolExecutionError
from lingshu_gate.domain.tool_structure import checked_json_size

MAX_ARGUMENT_BYTES = 1_048_576
MAX_SCHEMA_BYTES = 131_072
MAX_NODES = 8_192
MAX_DEPTH = 32
MAX_EXPANSION = 8_192
MAX_WORK = 262_144
VALIDATION_SECONDS = 2.0
WORKER_FLAG = "--gate-schema-validation-worker"
_workers = threading.BoundedSemaphore(4)


def _worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, WORKER_FLAG]
    return [sys.executable, "-m", __name__, "--worker"]


def _error(code: str) -> ToolExecutionError:
    return ToolExecutionError(code, "Arguments or the selected schema exceeded a supported validation boundary.",
        next_action="Use a bounded supported contract and describe the tool again before retrying.")


def _check_time(deadline: float, cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise _error("catalog_validation_cancelled")
    if time.monotonic() >= deadline:
        raise _error("catalog_validation_timeout")


def _nodes(value: Any, deadline: float, cancel: threading.Event | None, *, schema: bool) -> int:
    stack, count = [(value, 0)], 0
    while stack:
        _check_time(deadline, cancel)
        node, depth = stack.pop()
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise _error("catalog_validation_limit")
        if isinstance(node, dict):
            if len(node) > MAX_NODES - count:
                raise _error("catalog_validation_limit")
            if schema:
                if any(key in node for key in ("$dynamicRef", "$recursiveRef")):
                    raise _error("catalog_schema_unsupported")
                if "$ref" in node and (not isinstance(node["$ref"], str) or not node["$ref"].startswith("#/")):
                    raise _error("catalog_schema_unsupported")
            stack.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            if len(node) > MAX_NODES - count:
                raise _error("catalog_validation_limit")
            stack.extend((child, depth + 1) for child in node)
    return count


def _expansion(schema: dict[str, Any], deadline: float, cancel: threading.Event | None) -> int:
    """Memoize DAG costs, count each use, and reject cycles before evaluation."""
    memo: dict[int, tuple[int, int]] = {}
    active: set[int] = set()

    def reference(ref: str) -> Any:
        node: Any = schema
        for part in unquote(ref[2:]).split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict):
                node = node[part]
            elif isinstance(node, list) and part.isdecimal() and (part == "0" or not part.startswith("0")):
                node = node[int(part)]
            else:
                raise ValueError
        return node

    def cost(node: Any, level: int = 0) -> tuple[int, int]:
        _check_time(deadline, cancel)
        if level > MAX_DEPTH:
            raise _error("catalog_schema_complexity_limit")
        if not isinstance(node, (dict, list)):
            return 1, 0
        key = id(node)
        if key in active:
            raise _error("catalog_schema_complexity_limit")
        if key in memo:
            return memo[key]
        active.add(key)
        try:
            # Count definitions conservatively too. A mapping under properties
            # may legitimately name a property "$defs"; skipping by key alone
            # would omit an active schema subtree from the work budget.
            children = ([value for name, value in node.items() if name != "$ref"]
                        if isinstance(node, dict) else node)
            count, height = 1, 0
            for child in children:
                child_count, child_height = cost(child, level + 1)
                count += child_count
                height = max(height, child_height + 1)
                if count > MAX_EXPANSION or height > MAX_DEPTH:
                    raise _error("catalog_schema_complexity_limit")
            if isinstance(node, dict) and "$ref" in node:
                child_count, child_height = cost(reference(node["$ref"]), level + 1)
                count += child_count
                height = max(height, child_height + 1)
            if count > MAX_EXPANSION or height > MAX_DEPTH:
                raise _error("catalog_schema_complexity_limit")
            memo[key] = count, height
            return memo[key]
        finally:
            active.remove(key)

    return cost(schema)[0]


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any], *,
                       deadline: float | None = None, cancel: threading.Event | None = None) -> None:
    deadline = min(deadline if deadline is not None else float("inf"), time.monotonic() + VALIDATION_SECONDS)
    try:
        argument_nodes = _nodes(arguments, deadline, cancel, schema=False)
        _nodes(schema, deadline, cancel, schema=True)
        for value, limit, code in ((arguments, MAX_ARGUMENT_BYTES, "catalog_argument_limit"),
                                   (schema, MAX_SCHEMA_BYTES, "catalog_schema_limit")):
            try:
                checked_json_size(value, max_bytes=limit, max_nodes=MAX_NODES, max_depth=MAX_DEPTH)
            except ValueError:
                raise _error(code) from None
        if _expansion(schema, deadline, cancel) * argument_nodes > MAX_WORK:
            raise _error("catalog_schema_complexity_limit")
        def encode(value: Any) -> bytes:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        encoded_schema, encoded_arguments = encode(schema), encode(arguments)
        if len(encoded_schema) > MAX_SCHEMA_BYTES:
            raise _error("catalog_schema_limit")
        if len(encoded_arguments) > MAX_ARGUMENT_BYTES:
            raise _error("catalog_argument_limit")
    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
        raise _error("catalog_arguments_invalid") from None
    _check_time(deadline, cancel)
    if not _workers.acquire(blocking=False):
        raise _error("catalog_validation_busy")
    process: subprocess.Popen[bytes] | None = None
    writer: threading.Thread | None = None
    try:
        process = subprocess.Popen(_worker_command(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        pending = b'{"schema":' + encoded_schema + b',"arguments":' + encoded_arguments + b'}'
        channel = process.stdin
        assert channel is not None
        def send_input() -> None:
            try:
                channel.write(pending)
            except OSError:
                pass  # Cancellation closes the child's pipe; never log values.
            finally:
                try:
                    channel.close()
                except OSError:
                    pass
        writer = threading.Thread(target=send_input, daemon=True)
        writer.start()
        while True:
            _check_time(deadline, cancel)
            try:
                process.wait(timeout=min(.05, max(.001, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                continue
        assert process.stdout is not None
        output = process.stdout.read(16)
        if process.returncode != 0 or output.strip() != b"valid":
            raise _error("catalog_arguments_invalid")
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if writer is not None:
            writer.join(timeout=1)
        if process is not None and process.stdout is not None:
            process.stdout.close()
        _workers.release()


def _worker() -> None:
    # No inherited Gate runtime, lease or credential object. The parent kills
    # this process on cancellation/deadline, including regex CPU exhaustion.
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (2, 3))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except ImportError:
        pass  # Parent process termination supplies the portable wall-time bound.
    from jsonschema import FormatChecker
    from jsonschema.validators import validator_for
    from referencing import Registry
    from referencing.exceptions import NoSuchResource

    def no_remote(uri: str) -> Any:
        raise NoSuchResource(ref=uri)  # type: ignore[call-arg]

    try:
        raw = sys.stdin.buffer.read(MAX_ARGUMENT_BYTES + MAX_SCHEMA_BYTES + 64)
        payload = json.loads(raw)
        schema = payload["schema"]
        cls = validator_for(schema, default=None) if "$schema" in schema else validator_for(schema)
        if cls is None:
            raise ValueError
        cls.check_schema(schema)
        cls(schema, format_checker=FormatChecker(), registry=Registry(retrieve=no_remote)).validate(payload["arguments"])  # type: ignore[call-arg]
        sys.stdout.write("valid")
    except Exception:  # noqa: BLE001 - never print untrusted schemas or parameters
        raise SystemExit(1) from None


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit(2)
    _worker()
