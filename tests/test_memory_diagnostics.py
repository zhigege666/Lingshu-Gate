"""Memory diagnostics must never collect command arguments or environment."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from lingshu_gate import memory_diagnostics


def test_snapshot_and_log_keep_resources_without_reading_argument_or_environment_secrets(tmp_path, monkeypatch, caplog):
    process = tmp_path / "123"
    process.mkdir()
    (process / "status").write_text("Name:\tsynthetic-peer\nPid:\t123\nPPid:\t1\nVmRSS:\t42 kB\nVmSize:\t84 kB\nThreads:\t2\n")
    # These names deliberately do not match Gate's sensitive-key blacklist.
    command_secret, environment_secret = "Synthetic-Opaque-Argument", "Synthetic-Opaque-Environment"
    (process / "cmdline").write_bytes(f"synthetic-peer\0--opaque-value\0{command_secret}\0".encode())
    (process / "environ").write_bytes(f"OPAQUE_OPTION={environment_secret}\0".encode())
    monkeypatch.setattr(memory_diagnostics, "PROC_ROOT", tmp_path)
    original_read_bytes, original_read_text = Path.read_bytes, Path.read_text
    def read_bytes(path):
        assert path.name not in {"cmdline", "environ"}, "Sensitive procfs file must not be read"
        return original_read_bytes(path)
    def read_text(path, *args, **kwargs):
        assert path.name not in {"cmdline", "environ"}, "Sensitive procfs file must not be read"
        return original_read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "read_text", read_text)
    snapshot = memory_diagnostics.collect_memory_snapshot()
    assert snapshot["top_processes"] == [{"pid": 123, "ppid": 1, "rss_bytes": 42 * 1024,
        "vsz_bytes": 84 * 1024, "threads": 2, "command": "synthetic-peer", "source": "procfs"}]
    with caplog.at_level(logging.INFO):
        memory_diagnostics.log_memory_snapshot(logging.getLogger("synthetic-memory"), "gate.synthetic.memory", "Synthetic memory")
    logged_snapshot = caplog.records[-1].gate_memory
    assert logged_snapshot["top_processes"] == snapshot["top_processes"]
    output = json.dumps(snapshot) + caplog.text + json.dumps(logged_snapshot)
    assert command_secret not in output and environment_secret not in output
    assert '"args"' not in output and '"cmdline"' not in output and '"environ"' not in output
