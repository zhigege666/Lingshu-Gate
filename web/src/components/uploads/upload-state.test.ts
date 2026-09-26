import { describe, expect, it } from "vitest"
import { completeUploadAction, prepareUploadManifest, resultForUpload } from "./upload-state"

describe("upload action ownership", () => {
  it("retains upload analysis and generated Manifest across later save responses", () => {
    const analysis = { detected_runtime: "python", entrypoints: ["server.py"] }
    const manifest = { id: "project-a", launch: { args: ["", "server.py"] } }
    let results = completeUploadAction({}, { uploadId: "a", action: "upload", requestId: 1, data: { id: "a", analysis } })
    results = completeUploadAction(results, { uploadId: "a", action: "draft", requestId: 2, data: { upload_id: "a", manifest } })
    results = completeUploadAction(results, { uploadId: "a", action: "save", requestId: 3, data: { message: "saved", config: { id: "project-a" } } })
    expect(results.a.analysis).toBe(analysis)
    expect(results.a.manifest).toBe(manifest)
    expect(results.a.action).toBe("save")
  })

  it("does not show another upload's late result as the selected project's result", async () => {
    let complete: (value: unknown) => void = () => undefined
    const pending = new Promise(resolve => { complete = resolve })
    const selectedId = "b"
    const finish = pending.then(data => completeUploadAction({}, { uploadId: "a", action: "draft", requestId: 1, data }))
    complete({ upload_id: "a", manifest: { id: "from-a" } })
    const results = await finish
    expect(resultForUpload(results, selectedId)).toBeNull()
    expect(resultForUpload(results, "a")?.manifest?.id).toBe("from-a")
  })

  it("ignores an older operation that finishes after a newer result for the same upload", () => {
    const latest = completeUploadAction({}, { uploadId: "a", action: "draft", requestId: 3, data: { manifest: { id: "new" } } })
    const settled = completeUploadAction(latest, { uploadId: "a", action: "upload", requestId: 1, data: { id: "a", analysis: { stale: true } } })
    expect(settled).toBe(latest)
    expect(settled.a.manifest?.id).toBe("new")
  })
})

describe("upload Manifest submission", () => {
  it("keeps ordinary values lossless while moving one-time credentials to a separate payload", () => {
    const original = { id: "project", launch: { args: ["", " x ", "0"], env: { EMPTY: "", PADDED: " x " } }, unknown: [0, false, null, ""], user_credential_values: { demo: "test-only" } }
    const prepared = prepareUploadManifest(JSON.stringify(original))
    expect(prepared.manifest).toEqual({ id: original.id, launch: original.launch, unknown: original.unknown })
    expect(prepared.manifest).not.toHaveProperty("user_credential_values")
    expect(prepared.credentialValues).toEqual({ demo: "test-only" })
    expect(original.user_credential_values).toEqual({ demo: "test-only" })
  })

  it("rejects invalid JSON, non-object roots and non-string one-time values without inventing a valid document", () => {
    expect(() => prepareUploadManifest('{"id":')).toThrow()
    expect(() => prepareUploadManifest("[]")).toThrow()
    expect(() => prepareUploadManifest('{"user_credential_values":{"demo":false}}')).toThrow()
  })
})
