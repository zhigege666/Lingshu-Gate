"""Exercise Core startup with real Linux bind mounts and the image's service UID.

Run as a rootful Docker test operator. Only newly created temporary directories
and containers are changed; Gate itself always runs as 10001:10001 without caps.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
from typing import Any
import uuid


class SmokeFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def docker(*arguments: str) -> str:
    result = subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, timeout=45,
    )
    if result.returncode:
        raise SmokeFailure(f"docker {arguments[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def inspect_container(container: str) -> dict[str, Any]:
    return json.loads(docker("inspect", container))[0]


def request_readiness(port: int) -> tuple[int, dict[str, Any]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request("GET", "/readyz")
        response = connection.getresponse()
        body = response.read(64 * 1024)
        return response.status, json.loads(body)
    finally:
        connection.close()


def wait_ready(container: str, port: int, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = inspect_container(container)["State"]
        require(state["Running"], f"Core exited before readiness: exit={state['ExitCode']}")
        try:
            status, report = request_readiness(port)
            if status == 200:
                return report
        except (OSError, http.client.HTTPException, ValueError):
            pass
        time.sleep(1)
    raise SmokeFailure("Core did not become ready within the startup deadline")


def owned_directory(path: Path, uid: int = 10001, gid: int = 10001) -> Path:
    path.mkdir(mode=0o755)
    path.chmod(0o755)
    os.chown(path, uid, gid)
    return path


def create_container(
    image: str, platform: str | None, data: Path, config: Path, workspace: Path,
    containers: list[str],
) -> tuple[str, int]:
    args = [
        "create", "--name", f"lingshu-gate-bind-smoke-{uuid.uuid4().hex[:12]}",
        "--label", "io.lingshu.gate.test=bind-startup", "--user", "10001:10001",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=256", "--restart=no", "--publish", "127.0.0.1::8000",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,uid=10001,gid=10001",
        "--mount", f"type=bind,source={data},target=/data",
        "--mount", f"type=bind,source={config},target=/config",
        "--mount", f"type=bind,source={workspace},target=/workspace,readonly",
        "--env", "LINGSHU_GATE_DATA_DIR=/data",
        "--env", "LINGSHU_GATE_CONFIG_DIR=/config/mcp.d",
        "--env", "LINGSHU_GATE_DB_URL=sqlite:////data/gate.db",
    ]
    if platform:
        args += ["--platform", platform]
    container = docker(*args, image)
    containers.append(container)
    docker("start", container)
    info = inspect_container(container)
    binding = info["HostConfig"]["PortBindings"]["8000/tcp"][0]
    require(binding["HostIp"] == "127.0.0.1", "Smoke port must remain loopback-only")
    require(info["Config"]["User"] == "10001:10001", "Unexpected runtime identity")
    require(info["HostConfig"]["ReadonlyRootfs"], "Core root filesystem must be read-only")
    allocated = (info["NetworkSettings"]["Ports"] or {}).get("8000/tcp")
    return container, int(allocated[0]["HostPort"]) if allocated else 0


def positive_case(root: Path, image: str, platform: str | None, timeout: int, containers: list[str]) -> None:
    data = owned_directory(root / "data")
    owned_directory(data / "home")
    owned_directory(data / "cache")
    config = owned_directory(root / "config")
    workspace = owned_directory(root / "workspace")
    container, port = create_container(image, platform, data, config, workspace, containers)
    report = wait_ready(container, port, timeout)
    require(report["checks"]["database"]["ok"], "Fresh bind-mounted database is not ready")
    require(report["checks"]["configuration"]["ok"], "Creatable missing configuration must remain ready")
    require(report["checks"]["runtime"]["metadata"]["scan_status"] == "missing", "Missing scan must be explicit")
    require(not (config / "mcp.d").exists(), "Readiness must not create configuration directories")
    database = (data / "gate.db").stat()
    require((database.st_uid, database.st_gid) == (10001, 10001), "Database was not created by the service user")
    credentials = (data / "initial-admin-credentials.json").stat()
    require(
        stat.S_ISREG(credentials.st_mode) and credentials.st_size > 0,
        "Bootstrap credential file must be a nonempty regular file",
    )
    require(stat.S_IMODE(credentials.st_mode) == 0o600, "Bootstrap credential mode must remain 0600")

    directory = owned_directory(config / "mcp.d")
    status, report = request_readiness(port)
    require(status == 200 and report["checks"]["configuration"]["ok"], "New empty configuration directory must be ready")
    require(report["checks"]["runtime"]["metadata"]["scan_status"] == "missing", "Creating a directory must not imply a runtime rescan")
    directory.chmod(0o555)
    try:
        status, report = request_readiness(port)
        require(status == 503 and not report["checks"]["configuration"]["ok"], "Real UID must detect non-writable configuration")
    finally:
        directory.chmod(0o755)
    status, report = request_readiness(port)
    require(status == 200, "Restored isolated configuration permissions must restore readiness")
    print(json.dumps({"case": "writable_bind", "result": "passed", "uid": 10001,
                      "root_read_only": True, "configuration_transitions": ["missing_creatable", "directory", "not_writable", "directory"]}))


def negative_case(root: Path, image: str, platform: str | None, timeout: int, containers: list[str]) -> None:
    data = owned_directory(root / "denied-data", 99, 100)
    config = owned_directory(root / "denied-config")
    owned_directory(config / "mcp.d")
    workspace = owned_directory(root / "denied-workspace")
    container, _port = create_container(image, platform, data, config, workspace, containers)
    deadline = time.monotonic() + timeout
    state = inspect_container(container)["State"]
    while state["Running"] and time.monotonic() < deadline:
        time.sleep(1)
        state = inspect_container(container)["State"]
    require(not state["Running"] and state["ExitCode"] != 0, "Unwritable data bind must fail startup")
    require(not state["OOMKilled"], "Negative case must be a filesystem failure, not OOM")
    records = []
    for line in docker("logs", container).splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("event") == "gate.startup.path_failed":
            records.append(record)
    require(bool(records), "Startup failure must include a structured filesystem diagnostic")
    record = records[-1]
    require(record.get("component") == "database", "Failure must identify the database boundary")
    require((record.get("effective_uid"), record.get("effective_gid")) == (10001, 10001), "Failure must report the effective service identity")
    parent = record.get("parent", {})
    require(parent.get("path") == "/data", "Failure must identify the actual database parent")
    require((parent.get("owner_uid"), parent.get("owner_gid")) == (99, 100), "Failure must report observed bind ownership")
    require(parent.get("mode") == "0755" and parent.get("writable") is False, "Failure must report observed access facts")
    require(bool(record.get("reason_code")) and record["reason_code"] != "[REDACTED]", "Failure reason must remain machine-readable")
    unchanged = data.stat()
    require((unchanged.st_uid, unchanged.st_gid, stat.S_IMODE(unchanged.st_mode)) == (99, 100, 0o755), "Startup must not change host ownership or permissions")
    require(not any(data.iterdir()), "Failed startup must not substitute another database in the data directory")
    print(json.dumps({"case": "unwritable_bind", "result": "passed", "exit_code": state["ExitCode"],
                      "reason_code": record["reason_code"], "uid": record["effective_uid"], "owner": "99:100", "mode": "0755"}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--platform")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    require(os.name == "posix" and os.geteuid() == 0, "Run this isolated Linux test as a rootful Docker operator to prepare numeric bind ownership")
    require(args.timeout > 0, "Startup timeout must be positive")
    identity = docker("image", "inspect", "--format", "{{.Config.User}}", args.image)
    require(identity == "10001:10001", "The tested image must default to service user 10001:10001")
    containers: list[str] = []
    with tempfile.TemporaryDirectory(prefix="lingshu-gate-bind-smoke-") as temporary:
        try:
            root = Path(temporary)
            positive_case(root, args.image, args.platform, args.timeout, containers)
            negative_case(root, args.image, args.platform, args.timeout, containers)
        except BaseException:
            for container in containers:
                try:
                    print(docker("logs", "--tail", "50", container))
                except SmokeFailure:
                    pass
            raise
        finally:
            if containers:
                docker("rm", "--force", *containers)


if __name__ == "__main__":
    main()
