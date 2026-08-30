"""ToolRegistry snapshot and lock-boundary tests."""

from __future__ import annotations

import threading
import unittest

from lingshu_gate.models import ToolDefinition
from lingshu_gate.registry import ToolRecord, ToolRegistry


def definition(tool_id: str, generation: str) -> ToolDefinition:
    return ToolDefinition(
        id=tool_id,
        name=tool_id,
        description="concurrency fixture",
        permission="read",
        input_schema={"type": "object"},
        source="mcp",
        metadata={"server_id": "demo", "generation": generation},
    )


class ToolRegistryConcurrencyTest(unittest.TestCase):
    def test_handler_execution_does_not_hold_registry_lock(self) -> None:
        registry = ToolRegistry()
        entered = threading.Event()
        release = threading.Event()

        def blocking_handler(_: dict[str, object]) -> dict[str, object]:
            entered.set()
            self.assertTrue(release.wait(timeout=3))
            return {"ok": True}

        registry.register(definition("mcp.demo.blocking", "initial"), blocking_handler)
        invocation = threading.Thread(
            target=lambda: registry.invoke("mcp.demo.blocking", {})
        )
        invocation.start()
        self.assertTrue(entered.wait(timeout=1))

        registration = threading.Thread(
            target=lambda: registry.register(
                definition("mcp.demo.concurrent", "concurrent"),
                lambda _: {},
            )
        )
        registration.start()
        registration.join(timeout=1)
        self.assertFalse(
            registration.is_alive(),
            "register was blocked by a running tool handler",
        )

        release.set()
        invocation.join(timeout=3)
        self.assertFalse(invocation.is_alive())

    def test_replace_publishes_only_complete_snapshots(self) -> None:
        registry = ToolRegistry()
        old_records = tuple(
            ToolRecord(definition(f"mcp.demo.old-{index}", "old"), lambda _: {})
            for index in range(4)
        )
        new_records = tuple(
            ToolRecord(definition(f"mcp.demo.new-{index}", "new"), lambda _: {})
            for index in range(4)
        )
        registry.replace_by_metadata(
            "server_id",
            "demo",
            old_records,
            source="mcp",
        )
        old_ids = {record.definition.id for record in old_records}
        new_ids = {record.definition.id for record in new_records}
        finished = threading.Event()
        failures: list[set[str]] = []

        def writer() -> None:
            for index in range(500):
                registry.replace_by_metadata(
                    "server_id",
                    "demo",
                    new_records if index % 2 == 0 else old_records,
                    source="mcp",
                )
            finished.set()

        def reader() -> None:
            while not finished.is_set():
                snapshot = frozenset(
                    item.id
                    for item in registry.list_definitions()
                    if item.metadata.get("server_id") == "demo"
                )
                if snapshot not in {frozenset(old_ids), frozenset(new_ids)}:
                    failures.append(set(snapshot))
                    return

        writer_thread = threading.Thread(target=writer)
        reader_threads = [threading.Thread(target=reader) for _ in range(3)]
        for thread in reader_threads:
            thread.start()
        writer_thread.start()
        writer_thread.join(timeout=5)
        for thread in reader_threads:
            thread.join(timeout=5)

        self.assertFalse(writer_thread.is_alive())
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
