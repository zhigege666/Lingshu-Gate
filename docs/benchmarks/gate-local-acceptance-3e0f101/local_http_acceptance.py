"""Actual loopback HTTP and dependency-free stdio delivery acceptance.

Requires the run-owned launcher's separately authorized, regenerable fixture.
No browser, remote host, OAuth enablement, new credential or grant is used.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile

import httpx


def require(condition: bool, label: str) -> None:
    if not condition:
        raise RuntimeError(label)


def main() -> int:
    sys.path.insert(0, sys.argv[1])
    import run_owned_e2e as owned

    root = Path(sys.argv[2])
    layout = owned.read_layout(root)
    owned._require_execution_approval(root, layout)
    source = owned._prepared_inputs(layout)
    receipt: dict[str, object] = {
        "source_sha": owned.SOURCE_SHA,
        "transport": "actual loopback HTTP and actual stdio child",
        "fixture": "regenerable local synthetic accounts and data",
        "browser_executed": False,
        "nx5_executed": False,
        "oauth_enabled": False,
        "cases": [],
        "passed": False,
    }
    cases = receipt["cases"]

    def passed(name: str) -> None:
        cases.append({"name": name, "passed": True})

    def json_response(client, method, path, *, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        require(response.status_code == expected, "Unexpected HTTP status for " + method + " " + path.split("/")[1])
        return response.json()

    try:
        subprocess.Popen(
            [str(layout["python"]), "-I", "-B", str(Path(owned.__file__).resolve()),
             "fixture", "--root", str(root)],
            cwd=source / "web", start_new_session=True,
        )
        clients = [httpx.Client(base_url="http://127.0.0.1:18763", trust_env=False,
                                follow_redirects=False, timeout=5) for _ in range(3)]
        anonymous, viewer, admin = clients
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    health = anonymous.get("/healthz")
                    if health.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                require(time.monotonic() < deadline, "Owned fixture startup deadline")
                time.sleep(0.05)
            metadata = json_response(anonymous, "GET", "/v1/meta")
            require(metadata["version"] == "0.4.5", "Running source version differs")
            receipt["running_version"] = metadata["version"]
            passed("actual fixture health and running backend version")

            static = owned.verify_served(root)
            receipt["static_binding"] = static
            passed("all 115 Console assets served with exact SHA and OAuth routes disabled")

            html = anonymous.get("/", headers={"Accept": "text/html"})
            require(html.status_code == 200 and "text/html" in html.headers["content-type"], "Root HTML")
            require(html.headers.get("vary") == "Accept" and "no-store" in html.headers["cache-control"], "Root cache boundary")
            for accept in ["application/json", "application/json;q=0.5,text/html;q=1", "*/*"]:
                response = anonymous.get("/", headers={"Accept": accept})
                require(response.status_code == 200 and response.json() == metadata, "Programmatic discovery")
            require(anonymous.get("/", headers={"Accept": "text/html;q=0,application/json;q=0"}).status_code == 406, "Unacceptable root response")
            query = "?bookmark=one&bookmark=two&return=%2F%23%2FmyServers&label=a+b"
            for entry in ["/console", "/console/", "/console/index.html"]:
                response = anonymous.get(entry + query, headers={"Accept": "text/html"})
                require(response.status_code == 307 and response.headers["location"] == "/" + query, "Legacy query redirect")
            passed("root negotiation, no-store and all legacy redirect query bytes")

            inventory = layout["static_inventory"]["console"]
            assets = [(path, digest) for path, digest in inventory.items() if path.startswith("assets/")]
            for relative, digest in assets:
                fresh, legacy = anonymous.get("/" + relative), anonymous.get("/console/" + relative)
                require(fresh.status_code == legacy.status_code == 200, "Actual legacy asset status")
                require(hashlib.sha256(fresh.content).hexdigest() == digest and fresh.content == legacy.content, "Actual legacy asset SHA")
                require("immutable" in fresh.headers["cache-control"], "Hashed asset cache policy")
            for path in ["/assets/not-in-build.js", "/console/not-in-build.js", "/console/%2e%2e/pyproject.toml", "/assets/%2e%2e/pyproject.toml"]:
                require(anonymous.get(path).status_code == 404, "Unexpected or escaping asset path")
            receipt["legacy_hashed_assets_verified"] = len(assets)
            passed("actual root and legacy asset parity, missing assets and traversal rejection")

            require(anonymous.get("/v1/auth/me").status_code == 401, "Anonymous authentication")
            json_response(viewer, "POST", "/v1/auth/login", json={"username": "synthetic-viewer", "password": "Synthetic-viewer-123!"})
            json_response(viewer, "GET", "/v1/auth/me")
            for path in ["/v1/mcp/servers", "/v1/mcp/configs", "/v1/credentials", "/v1/builds", "/v1/projects/uploads"]:
                require(viewer.get(path).status_code == 403, "Viewer control-plane denial")
            for path in ["/v1/me/mcp-servers", "/v1/me/invocations"]:
                require(viewer.get(path).status_code == 200, "Viewer personal summary")
            passed("actual anonymous denial, viewer login, personal reads and five management denials")

            json_response(admin, "POST", "/v1/auth/login", json={"username": "admin", "password": "Synthetic-admin-123!"})
            fixture_path = source / "tests/test_real_delivery_journey.py"
            require(hashlib.sha256(fixture_path.read_bytes()).hexdigest() == layout["source_binding"]["files"]["tests/test_real_delivery_journey.py"], "Delivery fixture Git binding")
            module = ast.parse(fixture_path.read_text())
            server_source = next(ast.literal_eval(node.value) for node in module.body if isinstance(node, ast.Assign)
                                 and any(isinstance(target, ast.Name) and target.id == "SYNTHETIC_SERVER" for target in node.targets))
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(zipfile.ZipInfo("server.py", (2026, 1, 1, 0, 0, 0)), server_source)
                bundle.writestr(zipfile.ZipInfo("pyproject.toml", (2026, 1, 1, 0, 0, 0)),
                                '[project]\nname="synthetic-local-delivery"\nversion="0.0.1"\n')
            raw = archive.getvalue()
            receipt["bundle"] = {"included_files": ["pyproject.toml", "server.py"], "size_bytes": len(raw),
                                 "sha256": hashlib.sha256(raw).hexdigest(), "source": "Git-bound reviewed synthetic standard-library fixture"}
            uploaded = json_response(admin, "POST", "/v1/projects/upload",
                                     files={"file": ("synthetic-local-delivery.zip", raw, "application/zip")})
            options = {"upload_id": uploaded["id"], "runtime_override": "python", "project_root": ".",
                       "run_install": False, "run_build": False}
            preflight = json_response(admin, "POST", "/v1/builds/preflight", json={"upload_id": uploaded["id"], "runtime_override": "python"})
            owned._json_write(root / "artifacts/preflight.private.json", preflight)
            require(preflight["status"] in {"ok", "warning"}, "Preflight blocked")
            planned = json_response(admin, "POST", "/v1/builds/plan", json=options)
            require(planned["validation"]["ok"] and planned["plan"]["buildable"] and planned["plan"]["steps"] == [], "Exact copy-tree plan")
            receipt["build"] = {"runtime": "python", "steps": [], "run_install": False, "run_build": False,
                                "preflight_status": preflight["status"], "operation": "copy_tree artifact packaging"}
            passed("actual upload, preflight and dependency-free copy-tree plan")

            created = json_response(admin, "POST", "/v1/builds", json={**options, "timeout_seconds": 10})
            deadline = time.monotonic() + 20
            while True:
                built = json_response(admin, "GET", "/v1/builds/" + created["id"])
                if built["status"] in {"success", "failed", "cancelled", "unsupported"}:
                    break
                require(time.monotonic() < deadline, "Build terminal deadline")
                time.sleep(0.05)
            require(built["status"] == "success", "Actual build success")
            require(Path(built["artifact_dir"]).resolve().is_relative_to(root), "Artifact owned path")
            receipt["build"]["status"] = built["status"]
            passed("actual build terminal success with artifact inside owned root")

            server_id = "synthetic-owned-delivery"
            patch = {"launch": {"env": {"DELIVERY_MARKER": "synthetic-owned-main-v1"}},
                     "transport": {"protocol_version": "2026-07-28"}, "timeout_seconds": 3,
                     "restart_policy": {"enabled": False}}
            deploy_url = "/v1/builds/" + built["id"] + "/deploy"
            body = {"server_id": server_id, "start": True, "overwrite": False, "manifest_patch": patch,
                    "credential_policy": "require_none"}
            preview = json_response(admin, "POST", deploy_url + "/preview", json=body)
            for name in ["config_digest", "expected_previous_config_digest", "expected_credential_binding_digest"]:
                body["expected_config_digest" if name == "config_digest" else name] = preview[name]
            conflict = admin.post(deploy_url, json={**body, "expected_config_digest": "0" * 64})
            require(conflict.status_code in {400, 409}, "Deployment digest conflict")
            require(admin.get("/v1/mcp/configs/" + server_id).status_code == 404, "Digest mismatch created target")
            passed("actual wrong-digest deployment rejected without target creation")

            deployed = json_response(admin, "POST", deploy_url, json=body)
            require(deployed["status"] == "success" and deployed["runtime_started"] is True, "Actual deployment and startup")
            running = json_response(admin, "GET", "/v1/mcp/servers/" + server_id)
            require(running["status"] == "running" and running["tool_count"] == 1, "Running and actual discovery")
            output = json_response(admin, "POST", "/v1/tools/mcp." + server_id + ".snapshot/invoke", json={"arguments": {}})
            require(output["ok"] is True, "Actual stdio invocation")
            snapshot = json.loads(output["output"]["content"][0]["text"])
            require(snapshot["marker"] == "synthetic-owned-main-v1", "Actual stdio marker")
            require(Path(snapshot["cwd"]).resolve() == Path(built["artifact_dir"]).resolve(), "Actual stdio artifact cwd")
            require(owned.process_identity(int(snapshot["pid"])) is not None, "Actual stdio process identity")
            receipt["delivery"] = {"status": deployed["status"], "runtime_started": True, "runtime_status": running["status"],
                                   "tool_count": running["tool_count"], "stdio_invocation_verified": True,
                                   "artifact_cwd_verified": True, "classification_publication": "not performed",
                                   "new_permissions_granted": False, "full_skill_acceptance": False}
            passed("actual deployed stdio process, discovery and marker invocation")

            require(viewer.post("/v1/tools/mcp." + server_id + ".snapshot/invoke", json={"arguments": {}}).status_code == 403,
                    "New deployment expanded viewer permission")
            passed("new discovered tool remains unavailable to viewer without new grant")
            receipt["passed"] = True
        finally:
            for client in clients:
                client.close()
    except Exception as error:
        receipt["error_type"] = type(error).__name__
        if isinstance(error, RuntimeError):
            receipt["failed_check"] = str(error)
    owned._json_write(root / "artifacts/http-acceptance.json", receipt)
    print(json.dumps(receipt))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
