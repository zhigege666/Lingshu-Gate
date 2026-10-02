import { describe, expect, it } from "vitest"
import { apiErrorMessage } from "./http"

describe("structured API recovery errors", () => {
  it("shows digest conflict and recovery action without nested details", () => {
    expect(apiErrorMessage({ code: "config_digest_conflict", message: "Configuration changed", next_action: "Preview again", details: { input: "synthetic-private-value" } }, "409")).toBe("config_digest_conflict · Configuration changed · Preview again")
  })
  it("shows validation location without echoing supplied inputs", () => {
    expect(apiErrorMessage([{ loc: ["body", "manifest", "id"], msg: "Field required", input: { secret: "synthetic-private-value" } }], "422")).toBe("body.manifest.id: Field required")
  })
  it("keeps ordinary errors and falls back for unknown shapes", () => {
    expect(apiErrorMessage("Forbidden", "403")).toBe("Forbidden")
    expect(apiErrorMessage({ input: "synthetic-private-value" }, "500")).toBe("500")
  })
})
