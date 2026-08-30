export type DeploymentSideEffects = {
  start: boolean
  overwrite: boolean
}

export const DEFAULT_DEPLOYMENT_SIDE_EFFECTS: DeploymentSideEffects = Object.freeze({
  start: false,
  overwrite: false,
})

type SummaryLabels = {
  target: string
  overwrite: string
  start: string
  yes: string
  no: string
  unresolved: string
}

export function resolveDeploymentTarget(overrideId: string | undefined, manifestId: unknown, unresolved: string): string {
  const override = overrideId?.trim() || ""
  const manifest = typeof manifestId === "string" ? manifestId.trim() : ""
  return override || manifest || unresolved
}

export function formatDeploymentSummary(
  target: string,
  options: DeploymentSideEffects,
  labels: SummaryLabels,
): string {
  return [
    `${labels.target}: ${target || labels.unresolved}`,
    `${labels.overwrite}: ${options.overwrite ? labels.yes : labels.no}`,
    `${labels.start}: ${options.start ? labels.yes : labels.no}`,
  ].join("\n")
}

export function formatRollbackSummary(
  target: string,
  start: boolean,
  labels: Omit<SummaryLabels, "overwrite"> & { restore: string },
): string {
  return [
    `${labels.target}: ${target || labels.unresolved}`,
    `${labels.restore}: ${labels.yes}`,
    `${labels.start}: ${start ? labels.yes : labels.no}`,
  ].join("\n")
}
