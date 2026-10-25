import { request } from "./http"

export type HttpConnectionStage = { id: "configuration" | "http" | "authentication" | "handshake" | "tools"; status: "passed" | "failed" | "skipped"; code?: string }
export type HttpConnectionResult = {
  ok: boolean; status: string; code?: string; failed_stage?: string; elapsed_ms: number
  network_attempted: boolean; config_saved: false; trust_changed: false; registry_changed: false
  business_permissions_verified: false; stages: HttpConnectionStage[]; http_status?: number
  auth_scheme?: "bearer" | "basic"; oauth_advertised?: boolean
  protocol_version?: string; tool_count?: number
}

/** No WebCrypto requirement on LAN HTTP. The server binds a one-use CSRF ticket. */
export async function testHttpConnection(manifest: Record<string, unknown>, existingServerId?: string,
  expectedConfigDigest?: string, signal?: AbortSignal): Promise<HttpConnectionResult> {
  const body = JSON.stringify({ manifest, confirmed: true, timeout_seconds: 15,
    ...(existingServerId ? { existing_server_id: existingServerId, expected_config_digest: expectedConfigDigest } : {}) })
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (signal?.aborted) controller.abort()
  signal?.addEventListener("abort", abort, { once: true })
  const timer = setTimeout(abort, 35_000)
  try {
    const ticket = await request<{ csrf: string }>("/v1/mcp/external-configs/test/csrf", {
      method: "POST", body, cache: "no-store", signal: controller.signal,
    })
    return await request<HttpConnectionResult>("/v1/mcp/external-configs/test", {
      method: "POST", body, headers: { "Content-Type": "application/json", "X-CSRF-Token": ticket.csrf },
      cache: "no-store", signal: controller.signal,
    })
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener("abort", abort)
  }
}
