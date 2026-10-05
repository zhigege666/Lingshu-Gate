"""Compact DAGs and regex evaluation cannot consume unbounded Gate CPU/leases."""
import time
from threading import Event, Timer

import pytest

from lingshu_gate.application.schema_validation import validate_arguments
from lingshu_gate.registry import ToolExecutionError


def dag(levels):
    definitions = {"s0": {}}
    for level in range(1, levels + 1):
        definitions[f"s{level}"] = {"allOf": [{"$ref": f"#/$defs/s{level-1}"}] * 2}
    return {"$defs": definitions, "$ref": f"#/$defs/s{levels}"}


@pytest.mark.parametrize("levels", [0, 2, 5])
def test_typical_finite_local_dag_is_validated(levels):
    validate_arguments(dag(levels), {})


@pytest.mark.parametrize("levels", [12, 20, 30])
def test_compact_exponential_dag_is_rejected_before_process_evaluation(levels):
    started = time.monotonic()
    with pytest.raises(ToolExecutionError) as error:
        validate_arguments(dag(levels), {})
    assert error.value.code == "catalog_schema_complexity_limit"
    assert time.monotonic() - started < 1


def test_cycle_and_expanded_depth_are_rejected():
    with pytest.raises(ToolExecutionError):
        validate_arguments({"$defs": {"loop": {"$ref": "#/$defs/loop"}}, "$ref": "#/$defs/loop"}, {})
    deep = {}
    for _ in range(33):
        deep = {"child": deep}
    with pytest.raises(ToolExecutionError) as error:
        validate_arguments({"type": "object"}, deep)
    assert error.value.code == "catalog_validation_limit"


def test_catastrophic_regex_is_killed_on_deadline_and_worker_slot_is_reusable():
    schema = {"type": "object", "properties": {"text": {"type": "string", "pattern": "^(a+)+$"}}}
    started = time.monotonic()
    with pytest.raises(ToolExecutionError) as error:
        validate_arguments(schema, {"text": "a" * 20_000 + "!"}, deadline=started + .5)
    assert error.value.code == "catalog_validation_timeout"
    assert time.monotonic() - started < 1.5
    validate_arguments({"type": "object", "properties": {"value": {"pattern": "^[a-z]+$"}}}, {"value": "valid"})


def test_cancelled_validation_starts_no_worker():
    cancelled = Event()
    cancelled.set()
    with pytest.raises(ToolExecutionError) as error:
        validate_arguments({}, {}, cancel=cancelled)
    assert error.value.code == "catalog_validation_cancelled"


def test_cancellation_during_evaluation_terminates_child(monkeypatch):
    from lingshu_gate.application import schema_validation
    cancelled, children = Event(), []
    original = schema_validation.subprocess.Popen
    def started(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(schema_validation.subprocess, "Popen", started)
    timer = Timer(.3, cancelled.set)
    timer.start()
    try:
        with pytest.raises(ToolExecutionError) as error:
            validate_arguments({"properties": {"text": {"pattern": "^(a+)+$"}}},
                {"text": "a" * 20_000 + "!"}, cancel=cancelled)
        assert error.value.code == "catalog_validation_cancelled"
        assert len(children) == 1 and children[0].poll() is not None
    finally:
        timer.cancel()
        timer.join()
    validate_arguments({}, {})
