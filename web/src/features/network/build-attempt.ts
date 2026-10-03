import type { BuildRecord } from "@/api/builds"

export type BuildAttempt = { fingerprint: string; key: string; buildId: string | null }
const terminal = new Set(["success", "failed", "cancelled", "unsupported", "blocked"])

/** An uncertain write retains its key until the known task reaches a terminal state. */
export function confirmedBuildAttempt(previous: BuildAttempt | undefined, fingerprint: string, builds: BuildRecord[], newKey: () => string): BuildAttempt {
  if (previous) {
    const known = builds.find(build => build.id === previous.buildId)
    if (known && terminal.has(known.status)) return { fingerprint, key: newKey(), buildId: null }
    if (previous.fingerprint !== fingerprint) throw new Error("Existing build completion is unknown or still active. Reconcile that task before confirming changed inputs.")
    return previous
  }
  return { fingerprint, key: newKey(), buildId: null }
}
