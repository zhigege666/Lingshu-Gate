/** One public, bounded read of the running Gate version. No authentication or retries. */
export const GATE_VERSION_TIMEOUT_MS = 5_000
const VERSION_NUMBER = "(?:0|[1-9][0-9]*)"
const PRERELEASE = "(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
const VERSION_PATTERN = new RegExp(`^${VERSION_NUMBER}\\.${VERSION_NUMBER}\\.${VERSION_NUMBER}(?:-${PRERELEASE}(?:\\.${PRERELEASE})*)?$`)

export async function fetchGateVersion(signal?: AbortSignal): Promise<string> {
  const controller = new AbortController()
  let stop = () => controller.abort()
  let timer: ReturnType<typeof setTimeout> | undefined
  const stopped = new Promise<never>((_, reject) => {
    stop = () => {
      controller.abort()
      reject(new Error("Gate version is unavailable"))
    }
    timer = setTimeout(stop, GATE_VERSION_TIMEOUT_MS)
    signal?.addEventListener("abort", stop, { once: true })
    if (signal?.aborted) stop()
  })
  try {
    if (controller.signal.aborted) return await stopped
    return await Promise.race([stopped, (async () => {
      const response = await fetch("/healthz", {
        method: "GET", credentials: "omit", cache: "no-store", signal: controller.signal,
      })
      if (!response.ok) throw new Error("Gate version is unavailable")
      const data: unknown = await response.json()
      const version = data && typeof data === "object" && "version" in data ? data.version : null
      if (typeof version !== "string" || version.length > 96 || !VERSION_PATTERN.test(version)) {
        throw new Error("Gate version is unavailable")
      }
      return version
    })()])
  } finally {
    if (timer !== undefined) clearTimeout(timer)
    signal?.removeEventListener("abort", stop)
  }
}
