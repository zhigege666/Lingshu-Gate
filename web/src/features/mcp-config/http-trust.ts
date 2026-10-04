/** Syntax only. Trust is always decided by the service-owned administrator API. */
export function privateHttpOrigin(endpoint: unknown): { ip: string; port: number } | null {
  if (typeof endpoint !== "string" || !/^http:\/\//i.test(endpoint) || /[\s\\?#]/.test(endpoint)) return null
  const match = /^http:\/\/([^/]+)(?:\/.*)?$/i.exec(endpoint)
  if (!match || match[1].includes("@")) return null
  const ip = match[1].split(":")[0]
  const parts = ip.split(".")
  if (parts.length !== 4 || parts.some(part => !/^(0|[1-9][0-9]{0,2})$/.test(part) || Number(part) > 255)) return null
  const [a, b] = parts.map(Number)
  if (!(a === 10 || a === 172 && b >= 16 && b <= 31 || a === 192 && b === 168)) return null
  try {
    const url = new URL(endpoint)
    if (url.hostname !== ip || url.username || url.password) return null
    const port = Number(url.port || 80)
    if (port < 1 || port > 65535 || /[\u0000-\u001f\u007f]/.test(decodeURIComponent(url.pathname))) return null
    return { ip, port }
  } catch { return null }
}
