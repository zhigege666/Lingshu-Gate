import { expect, it } from "vitest"
import { deliveryDraftRequest, manifestPatch, mergeManifestPatch } from "./delivery-draft"

it("preserves upload configuration and deployment choices when attaching a new build", () => {
  const body = deliveryDraftRequest({ upload_id: "u", revision: 3, manifest_patch: { name: "custom" }, server_id: "target", build_id: "old", deployment_id: null, start: true, overwrite: true, package_manager_override: { name: "pnpm", version: "9.15.4", lockfile: "pnpm-lock.yaml" } }, { build_id: "new" })
  expect(body).toMatchObject({ expected_revision: 3, manifest_patch: { name: "custom" }, server_id: "target", build_id: "new", start: true, overwrite: true })
  expect(body).not.toHaveProperty("upload_id")
  expect(body).not.toHaveProperty("revision")
  expect(body.package_manager_override).toEqual({ name: "pnpm", version: "9.15.4", lockfile: "pnpm-lock.yaml" })
})

it("keeps generated artifact paths while merging only user configuration changes", () => {
  const source = { launch: { cwd: "/source", command: "node", env: { MODE: "old", REMOVE: "yes" } } }
  const edited = { launch: { cwd: "/source", command: "node", env: { MODE: "new" } } }
  const patch = manifestPatch(source, edited)
  expect(patch).toEqual({ launch: { env: { MODE: "new", REMOVE: null } } })
  expect(mergeManifestPatch({ launch: { cwd: "/artifact", command: "node", env: { MODE: "old", REMOVE: "yes" } } }, patch)).toEqual({ launch: { cwd: "/artifact", command: "node", env: { MODE: "new" } } })
})
