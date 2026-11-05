import type { DeploymentPreview } from "@/api/builds"

/** Ordinary first deployments use the explicit Deploy action as consent. */
export function requiresDeploymentConfirmation(preview: Pick<DeploymentPreview, "server_id" | "interrupts_existing_service" | "expected_previous_config_digest">, expectedTarget: string, overwrite: boolean): boolean {
  return overwrite || preview.interrupts_existing_service || Boolean(preview.expected_previous_config_digest) || !expectedTarget || preview.server_id !== expectedTarget
}

/** Rollback options belong to one deployment, never to the table selection. */
export function rollbackStartFor(option: { deploymentId: string; start: boolean }, deploymentId: string): boolean {
  return option.deploymentId === deploymentId && option.start
}

export function rollbackResultError(server: Record<string, unknown> | null | undefined, serverId: string, start: boolean): string | null {
  if (server?.id === serverId && (start ? server.status === "running" : ["loaded", "stopped", "external", "disabled"].includes(String(server.status)))) return null
  return String(server?.last_error || "Rollback outcome is not confirmed. Inspect the target service before retrying.")
}
