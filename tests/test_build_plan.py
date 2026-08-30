"""Node 构建计划按需安装与零步骤打包测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lingshu_gate.build_plan import build_plan, validate_plan
from lingshu_gate.build_preflight import run_build_preflight


def _node_preflight_metadata(**overrides: object) -> dict[str, object]:
    metadata: dict[str, object] = {
        "has_package_json": True,
        "has_package_lock": False,
        "has_pnpm_lock": False,
        "has_yarn_lock": False,
        "package_scripts": ["start"],
        "node_install_required": False,
        "node_install_reason": "No Node dependencies or install lifecycle scripts detected",
    }
    metadata.update(overrides)
    return metadata


class BuildPlanTest(unittest.TestCase):
    def test_node_project_without_dependencies_skips_install_and_packages_directly(self) -> None:
        plan = build_plan(
            {
                "runtime": "node",
                "project_root_dir": ".",
                "metadata": _node_preflight_metadata(),
            }
        )

        self.assertEqual(plan["steps"], [])
        self.assertTrue(any("No Node dependencies" in warning for warning in plan["warnings"]))
        self.assertFalse(plan["manifest"]["resolve_after_build"])
        self.assertIn("after artifact packaging", plan["notes"][0])

    def test_node_project_with_dependencies_still_installs_without_lockfile(self) -> None:
        plan = build_plan(
            {
                "runtime": "node",
                "project_root_dir": ".",
                "metadata": _node_preflight_metadata(
                    node_install_required=True,
                    node_install_reason="Node dependency groups present: dependencies",
                ),
            }
        )

        self.assertEqual(plan["steps"][0]["command"], ["npm", "install"])
        self.assertEqual(plan["steps"][0]["reason"], "Node dependency groups present: dependencies")

    def test_node_project_with_lockfile_uses_ci_when_install_is_required(self) -> None:
        plan = build_plan(
            {
                "runtime": "node",
                "project_root_dir": ".",
                "metadata": _node_preflight_metadata(
                    has_package_lock=True,
                    node_install_required=True,
                    node_install_reason="Node dependency groups present: dependencies",
                ),
            }
        )

        self.assertEqual(plan["steps"][0]["command"], ["npm", "ci"])

    def test_node_install_lifecycle_requires_install_even_without_dependencies(self) -> None:
        plan = build_plan(
            {
                "runtime": "node",
                "project_root_dir": ".",
                "metadata": _node_preflight_metadata(
                    node_install_required=True,
                    node_install_reason="Node install lifecycle scripts present: prepare",
                ),
            }
        )

        self.assertEqual(plan["steps"][0]["command"], ["npm", "install"])

    def test_plan_validation_rejects_commands_not_generated_for_the_step(self) -> None:
        plan = build_plan(
            {
                "runtime": "node",
                "project_root_dir": ".",
                "metadata": _node_preflight_metadata(package_scripts=["build", "start"]),
            },
            run_install=False,
        )
        plan["steps"][0]["command"] = ["npm", "run", "release"]

        validation = validate_plan(plan)

        self.assertFalse(validation["ok"])
        self.assertTrue(any("does not match the generated command" in error for error in validation["errors"]))

    def test_preflight_derives_install_requirement_from_package_json(self) -> None:
        tools_cache = {
            name: {"available": True, "path": name, "version": "test", "error": ""}
            for name in ("node", "npm", "npx", "python", "python3", "pip", "pip3")
        }
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            (root / "package.json").write_text(
                json.dumps({"name": "plain-mcp", "scripts": {"start": "node index.js"}}),
                encoding="utf-8",
            )
            (root / "index.js").write_text("console.log('ok');\n", encoding="utf-8")

            preflight = run_build_preflight(
                {"root_dir": str(root)},
                runtime_override="node",
                tools_cache=tools_cache,
            )

        self.assertFalse(preflight["metadata"]["node_install_required"])
        self.assertEqual(preflight["metadata"]["node_dependency_groups"], [])
        self.assertEqual(build_plan(preflight)["steps"], [])


if __name__ == "__main__":
    unittest.main()
