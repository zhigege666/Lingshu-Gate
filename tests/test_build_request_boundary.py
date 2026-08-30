"""REST request boundary tests for generated build plans."""

from __future__ import annotations

import unittest
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lingshu_gate.build_deploy_routes import register_build_deploy_routes


class RecordingBuildStore:
    def __init__(self) -> None:
        self.plan_calls: list[dict[str, Any]] = []
        self.build_calls: list[dict[str, Any]] = []
        self.deploy_calls: list[dict[str, Any]] = []
        self.rollback_calls: list[dict[str, Any]] = []

    def plan_upload(self, upload_id: str, **options: Any) -> dict[str, Any]:
        self.plan_calls.append({"upload_id": upload_id, **options})
        return {"preflight": {}, "plan": {}}

    def build_upload(self, upload_id: str, **options: Any) -> dict[str, Any]:
        self.build_calls.append({"upload_id": upload_id, **options})
        return {"id": "build-request-boundary", "status": "queued"}

    def deploy_build(self, build_id: str, **options: Any) -> dict[str, Any]:
        self.deploy_calls.append({"build_id": build_id, **options})
        return {"id": "deployment-request-boundary", "status": "success"}

    def rollback_deployment(
        self,
        deployment_id: str,
        **options: Any,
    ) -> dict[str, Any]:
        self.rollback_calls.append({"deployment_id": deployment_id, **options})
        return {"message": "rolled back"}


class BuildRequestBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RecordingBuildStore()
        app = FastAPI()
        register_build_deploy_routes(app, self.store, lambda: None)  # type: ignore[arg-type]
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

    def test_plan_rejects_fields_outside_the_generated_plan_contract(self) -> None:
        response = self.client.post(
            "/v1/builds/plan",
            json={"upload_id": "upload-request-boundary", "commands": [["npm", "run", "publish"]]},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.store.plan_calls, [])

    def test_create_rejects_fields_outside_the_generated_plan_contract(self) -> None:
        response = self.client.post(
            "/v1/builds",
            json={"upload_id": "upload-request-boundary", "commands": [["npm", "run", "publish"]]},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.store.build_calls, [])

    def test_deploy_and_rollback_default_optional_side_effects_to_false(self) -> None:
        deploy = self.client.post("/v1/builds/build-1/deploy", json={})
        rollback = self.client.post("/v1/deployments/deployment-1/rollback", json={})

        self.assertEqual(deploy.status_code, 200, deploy.text)
        self.assertEqual(rollback.status_code, 200, rollback.text)
        self.assertEqual(
            self.store.deploy_calls,
            [
                {
                    "build_id": "build-1",
                    "server_id": None,
                    "start": False,
                    "overwrite": False,
                }
            ],
        )
        self.assertEqual(
            self.store.rollback_calls,
            [{"deployment_id": "deployment-1", "start": False}],
        )

    def test_deploy_and_rollback_reject_unknown_or_coerced_fields(self) -> None:
        deploy_unknown = self.client.post(
            "/v1/builds/build-1/deploy",
            json={"unexpected": True},
        )
        deploy_coerced = self.client.post(
            "/v1/builds/build-1/deploy",
            json={"start": "false"},
        )
        rollback_unknown = self.client.post(
            "/v1/deployments/deployment-1/rollback",
            json={"unexpected": True},
        )
        rollback_coerced = self.client.post(
            "/v1/deployments/deployment-1/rollback",
            json={"start": "false"},
        )

        self.assertEqual(deploy_unknown.status_code, 422, deploy_unknown.text)
        self.assertEqual(deploy_coerced.status_code, 422, deploy_coerced.text)
        self.assertEqual(rollback_unknown.status_code, 422, rollback_unknown.text)
        self.assertEqual(rollback_coerced.status_code, 422, rollback_coerced.text)
        self.assertEqual(self.store.deploy_calls, [])
        self.assertEqual(self.store.rollback_calls, [])


if __name__ == "__main__":
    unittest.main()
