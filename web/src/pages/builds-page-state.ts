/** Rollback options belong to one deployment, never to the table selection. */
export function rollbackStartFor(option: { deploymentId: string; start: boolean }, deploymentId: string): boolean {
  return option.deploymentId === deploymentId && option.start
}

export function rollbackResultError(server: Record<string, unknown> | null | undefined, serverId: string, start: boolean): string | null {
  if (server?.id === serverId && (start ? server.status === "running" : ["loaded", "stopped", "external", "disabled"].includes(String(server.status)))) return null
  return String(server?.last_error || "Rollback outcome is not confirmed. Inspect the target service before retrying.")
}
