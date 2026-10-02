import {apiErrorMessage} from './http'

export const AUTH_REQUEST_TIMEOUT_MS = 15_000
export class AuthRequestError extends Error {
  constructor(message: string, public readonly status?: number, public readonly timedOut = false) { super(message); this.name = 'AuthRequestError' }
}

/** Bounds both response headers and body. A timed-out write is never replayed. */
export async function authRequest<T>(path: string, body?: Record<string, unknown>, method?: string): Promise<T> {
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new AuthRequestError('Authentication request timed out; its result is not confirmed.', undefined, true))
      controller.abort()
    }, AUTH_REQUEST_TIMEOUT_MS)
  })
  try {
    return await Promise.race([timeout, (async () => {
      const response = await fetch(path, {
        method: method || (body ? 'POST' : 'GET'), credentials: 'include', signal: controller.signal,
        headers: body ? {'Content-Type': 'application/json'} : undefined,
        body: body ? JSON.stringify(body) : undefined,
      })
      const text = await response.text()
      let data: Record<string, unknown>
      try { data = text ? JSON.parse(text) : {} }
      catch { throw new AuthRequestError('The authentication service returned an invalid response.', response.status) }
      if (!response.ok) throw new AuthRequestError(apiErrorMessage(data?.detail, `HTTP ${response.status}`), response.status)
      return data as T
    })()])
  } finally { if (timer !== undefined) clearTimeout(timer) }
}
