import { identityAccessApi } from "@/api/identity-access"
import { observabilityApi } from "@/api/observability"
import { serversRuntimeApi } from "@/api/servers-runtime"

/** Aggregated API surface for console pages. */
export const api = {
  ...observabilityApi,
  ...identityAccessApi,
  ...serversRuntimeApi,
}

export * from "@/api/delivery-builds"
export * from "@/api/identity-access"
export * from "@/api/observability"
export * from "@/api/servers-runtime"
