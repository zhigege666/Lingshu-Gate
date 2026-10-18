import { parsePolicyJson } from "@/features/argument-policy/json"

export type ArgumentRule = { id: string; pointer: string } & (
  { operator: "equals"; value: unknown } | { operator: "allowed_values"; values: unknown[] } |
  { operator: "number_range"; minimum?: number | null; maximum?: number | null } | { operator: "string_prefix"; prefix: string })
export type ArgumentPolicy = { tool_id: string; revision: number; enabled: boolean; rules: ArgumentRule[] }
export type ArgumentPolicyWrite = { expected_revision: number; enabled: boolean; rules: ArgumentRule[] }
export type ArgumentPreview = { allowed: boolean; draft: true; execution: "not_invoked"; rule_id?: string; pointer?: string; reason?: string }

export class ArgumentPolicyRequestError extends Error {
  constructor(public status: number, public code: string) { super(code) }
}

async function policyRequest<T>(path: string, init: RequestInit, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (signal?.aborted) abort()
  signal?.addEventListener("abort", abort, { once: true })
  const timer = setTimeout(abort, 15_000)
  try {
    const response = await fetch(path, { credentials: "include", cache: "no-store", ...init, signal: controller.signal })
    const text = await response.text()
    if (!response.ok) {
      let code = "argument_policy_request_failed"
      try {
        const body = JSON.parse(text) as { detail?: { code?: unknown } }
        if (typeof body.detail?.code === "string" && /^[a-z_]{1,80}$/.test(body.detail.code)) code = body.detail.code
      } catch { /* Do not show arbitrary server text or input-bearing details. */ }
      throw new ArgumentPolicyRequestError(response.status, code)
    }
    // Response envelopes add fields and nesting outside the rules subtree.
    // policyDraft separately enforces the unchanged rules budget.
    return parsePolicyJson(text, 131_072, { maxDepth: 32, maxNodes: 16_384 }) as T
  } catch (cause) {
    if (cause instanceof ArgumentPolicyRequestError) throw cause
    if (controller.signal.aborted) throw new ArgumentPolicyRequestError(0, "argument_policy_request_timeout")
    throw cause
  } finally { clearTimeout(timer); signal?.removeEventListener("abort", abort) }
}

const pathFor = (id: string) => "/v1/tools/" + encodeURIComponent(id) + "/argument-policy"
export const argumentPolicyApi = {
  get: (id: string, signal?: AbortSignal) => policyRequest<ArgumentPolicy>(pathFor(id), {}, signal),
  async save(id: string, draft: ArgumentPolicyWrite, signal?: AbortSignal): Promise<ArgumentPolicy> {
    // The exact body string owns both the ticket and the write; no canonicalizer.
    const body = JSON.stringify(draft)
    const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body))
    const digest = Array.from(new Uint8Array(hash), value => value.toString(16).padStart(2, "0")).join("")
    const ticket = await policyRequest<{ csrf: string }>(pathFor(id) + "/csrf?request_digest=" + digest, { method: "POST" }, signal)
    return policyRequest<ArgumentPolicy>(pathFor(id), { method: "PUT", headers: { "Content-Type": "application/json", "X-CSRF-Token": ticket.csrf }, body }, signal)
  },
  preview: (id: string, draft: ArgumentPolicyWrite, arguments_: Record<string, unknown>, signal?: AbortSignal) =>
    policyRequest<ArgumentPreview>(pathFor(id) + "/preview", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...draft, arguments: arguments_ }) }, signal),
}
